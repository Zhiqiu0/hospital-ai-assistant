"""Sentry tunnel endpoint（services/api/v1/sentry_tunnel.py）

治本动机（2026-05-25）：
  医生浏览器装的 ad-blocker（uBlock / AdGuard 等）或医院出口防火墙会拦截
  *.ingest.sentry.io 海外域名 → Sentry 上报丢失，运维仪表盘看不到故障。
  Tunnel 让前端把 envelope POST 到自己后端代理（同源域名）→ 后端转发到上游 ingest，
  ad-blocker 不识别同源域名就放行。

参考：https://docs.sentry.io/platforms/javascript/troubleshooting/#using-the-tunnel-option

安全护栏（防 SSRF / 防滥用 / 防 quota 爆掉）：
  1. 上游 host 必须匹配 settings.sentry_dsn 解析出来的 host（DSN whitelist 防 SSRF）
  2. body < 100KB（防超大 payload 拖垮代理）
  3. 每 IP 每秒 10 次（Redis incr 简易滑窗）
  4. 5s 超时（上游 sentry.io 挂了不阻塞医生页面）
  5. fire-and-forget：上游失败不抛 5xx，返回 status 字段让前端忽略

为什么不加 user auth：
  Sentry SDK v8 的 tunnel option 是 SDK 内部 fetch，不走 axios，默认不带 Authorization。
  加 auth 会导致未登录页面（如登录页）的报错上报不上去，跟"用 Sentry 看登录 bug"初衷冲突。
  业界标准做法（Vercel / Sentry 官方示例）也不加 user auth —— 由上面 4 道护栏兜底。
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings
from app.services.redis_cache import redis_cache


router = APIRouter()
logger = logging.getLogger(__name__)


# ── 配置常量 ──────────────────────────────────────────────────────────────────
# 100KB 足够覆盖单个 envelope（含 breadcrumbs + stack trace），异常 payload 会更大
# 但我们前端已经关了 session replay / profiling，envelope 一般 < 20KB
MAX_BODY_BYTES = 100 * 1024
# rate limit：每 IP 每秒 10 次。Sentry SDK 一般合并 envelope 不会刷请求，10/s 充裕
RATE_LIMIT_WINDOW_SEC = 1
RATE_LIMIT_MAX_COUNT = 10
# 上游超时：5s 够，超过说明 sentry.io 自己挂了
UPSTREAM_TIMEOUT_SEC = 5.0


def _parse_dsn_host_and_project(dsn: str) -> Optional[Tuple[str, str]]:
    """从 Sentry DSN 解析出 (host, project_id)。

    DSN 格式：https://[public_key]@oXXX.ingest.us.sentry.io/[project_id]
    返回 (oXXX.ingest.us.sentry.io, project_id) 或 None（解析失败）。
    """
    if not dsn:
        return None
    try:
        parsed = urlparse(dsn)
        host = parsed.hostname
        project_id = parsed.path.strip("/")
        if not host or not project_id:
            return None
        return host, project_id
    except Exception:
        return None


async def _check_rate_limit(ip: str) -> bool:
    """简易 IP rate limit：Redis INCR + EXPIRE 实现 1 秒滑窗。

    Returns:
        True = 通过；False = 超限。Redis 不可用时一律通过（不为可观测性堵业务）。
    """
    client = redis_cache._get_client()
    if client is None:
        return True
    try:
        key = f"sentry_tunnel_rl:{ip}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, RATE_LIMIT_WINDOW_SEC)
        return count <= RATE_LIMIT_MAX_COUNT
    except Exception:
        # Redis 抖动不影响可观测性
        return True


@router.post("/sentry-tunnel", status_code=status.HTTP_200_OK)
async def sentry_tunnel(request: Request) -> dict:
    """透传前端 Sentry SDK envelope 到上游 ingest。

    流程：
      1. 后端没配 SENTRY_DSN → 直接 200 静默（开发环境）
      2. rate limit 检查
      3. 读 body，检查 size
      4. 解析 envelope 第一行 header 拿到 DSN，对比 host 防 SSRF
      5. POST 到 https://{host}/api/{project_id}/envelope/，5s 超时
      6. 返回 {"status": "ok" | "upstream-failed" | "no-dsn"}
    """
    # 1. 后端没配 SENTRY_DSN → tunnel 无意义，前端可忽略
    upstream = _parse_dsn_host_and_project(settings.sentry_dsn or "")
    if not upstream:
        return {"status": "no-dsn"}
    upstream_host, upstream_project = upstream

    # 2. rate limit
    ip = request.client.host if request.client else "unknown"
    if not await _check_rate_limit(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limited",
        )

    # 3. body 大小限制
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="payload too large",
        )

    # 4. 解析 envelope 第一行 header，对比 dsn host 防 SSRF
    try:
        first_line = body.split(b"\n", 1)[0]
        header = json.loads(first_line)
        envelope_dsn = header.get("dsn", "")
        envelope_parsed = _parse_dsn_host_and_project(envelope_dsn)
        if not envelope_parsed or envelope_parsed[0] != upstream_host:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="dsn host mismatch",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bad envelope",
        )

    # 5. 透传到上游 ingest endpoint
    url = f"https://{upstream_host}/api/{upstream_project}/envelope/"
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SEC) as cli:
            resp = await cli.post(
                url,
                content=body,
                headers={"Content-Type": "application/x-sentry-envelope"},
            )
            # 上游 200/202 都算成功；4xx 5xx 也不抛（不让 Sentry 故障影响业务）
            return {"status": "ok", "upstream_status": resp.status_code}
    except Exception as exc:
        # 上游挂了/超时 → 静默丢弃（fire-and-forget），不污染业务
        logger.warning("sentry_tunnel: upstream_failed host=%s err=%s", upstream_host, exc)
        return {"status": "upstream-failed"}
