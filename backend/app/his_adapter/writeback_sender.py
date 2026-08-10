"""病历回写发送：组装 payload → 按通道下发（写入 + 刷新），带超时与重试。

通道选择（规范第 7 章）：HIS WebSocket 长连接在线时优先走方案 B（消息下行 + ack）；
离线时回落方案 A（HTTP POST 签名调用）；两者均不可用返回 skipped 安全空跑。

依赖配置（待厂商确认后填，见 config.py）：
  his_writeback_url / his_writeback_refresh_url / his_writeback_app_id /
  his_writeback_app_secret / his_writeback_timeout_seconds / his_writeback_max_retries

设计要点：
  - 回写地址未配置时直接返回 skipped（不报错），便于联调前空跑、上线前安全。
  - 签名方向：我方调 HIS，用 HIS 分配给我方的 his_writeback_app_* 凭证签名。
  - body_raw 固定序列化一次，签名与发送用同一份；重试时只换 timestamp/nonce/sign。
  - 写入成功后再调刷新（刷新地址未配置则跳过，由 HIS 自动刷新场景兼容）。
"""
import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.signing import compute_sign
from app.his_adapter.writeback_builder import build_writeback_payload
from app.his_adapter.ws_manager import his_ws_manager


@dataclass
class WritebackResult:
    """回写结果。status: success | skipped | write_failed | refresh_failed。"""

    ok: bool
    status: str
    message: str = ""
    his_doc_id: Optional[str] = None
    http_status: Optional[int] = None


def _signed_headers(body_raw: str) -> dict:
    """按规范给回写请求生成签名头（每次调用换新的 timestamp/nonce）。"""
    app_id = settings.his_writeback_app_id
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(app_id, ts, nonce, body_raw, settings.his_writeback_app_secret)
    return {
        "X-App-Id": app_id,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Sign": sign,
        "Content-Type": "application/json; charset=utf-8",
    }


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, body_raw: str, max_retries: int
) -> httpx.Response:
    """POST body_raw 到 url；网络异常或 5xx 时重试，最多 max_retries 次。"""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.post(
                url, content=body_raw.encode("utf-8"), headers=_signed_headers(body_raw)
            )
            if resp.status_code >= 500 and attempt < max_retries:
                continue
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
    # 理论不可达：循环要么 return 要么 raise
    raise last_exc  # type: ignore[misc]


def _envelope_code(resp: httpx.Response) -> tuple[int, str, dict]:
    """解析 HIS 返回的统一信封，返回 (code, message, data)；非 JSON 视为失败。"""
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        return -1, "响应非 JSON", {}
    code = body.get("code", -1)
    try:
        code = int(code)
    except (ValueError, TypeError):
        code = -1
    return code, str(body.get("message", "")), (body.get("data") or {})


async def send_writeback(
    db: AsyncSession,
    encounter_id: str,
    app_version: str = "1.0.0",
    client: Optional[httpx.AsyncClient] = None,
) -> WritebackResult:
    """把一次接诊的病历回写到 HIS（写入 + 刷新）。

    Args:
        db:           异步会话
        encounter_id: 接诊 ID
        app_version:  MediScribe 版本（写进 meta）
        client:       可注入的 httpx 客户端（测试用）；为空则内部创建

    Returns:
        WritebackResult
    """
    payload = await build_writeback_payload(db, encounter_id, app_version=app_version)

    # 通道选择：WS 长连接在线 → 方案 B；否则有 HTTP 地址 → 方案 A；都没有 → 空跑
    if his_ws_manager.has_connection():
        return await _send_via_ws(payload)
    if not settings.his_writeback_url:
        return WritebackResult(ok=False, status="skipped", message="回写地址未配置且 WS 未连接")
    body_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    max_retries = settings.his_writeback_max_retries

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.his_writeback_timeout_seconds)
    try:
        # 1. 写入
        try:
            resp = await _post_with_retry(client, settings.his_writeback_url, body_raw, max_retries)
        except httpx.HTTPError as exc:
            return WritebackResult(ok=False, status="write_failed", message=f"网络异常：{exc}")
        if resp.status_code != 200:
            return WritebackResult(
                ok=False, status="write_failed",
                message=f"HTTP {resp.status_code}", http_status=resp.status_code,
            )
        code, message, data = _envelope_code(resp)
        if code != 0:
            return WritebackResult(
                ok=False, status="write_failed",
                message=f"HIS 返回 code={code} {message}", http_status=200,
            )
        his_doc_id = data.get("record_id") or data.get("doc_id") or data.get("id")

        # 2. 刷新（刷新地址未配置则跳过）
        if settings.his_writeback_refresh_url:
            target = f"{payload['record_type']}_record"
            refresh_raw = json.dumps(
                {"visit_id": payload["visit_id"], "target": target},
                ensure_ascii=False, sort_keys=True,
            )
            try:
                rresp = await _post_with_retry(
                    client, settings.his_writeback_refresh_url, refresh_raw, max_retries
                )
            except httpx.HTTPError as exc:
                return WritebackResult(
                    ok=False, status="refresh_failed",
                    message=f"刷新网络异常：{exc}", his_doc_id=his_doc_id,
                )
            if rresp.status_code != 200:
                return WritebackResult(
                    ok=False, status="refresh_failed",
                    message=f"刷新 HTTP {rresp.status_code}", his_doc_id=his_doc_id,
                )

        return WritebackResult(ok=True, status="success", his_doc_id=his_doc_id, http_status=200)
    finally:
        if own_client:
            await client.aclose()


async def _send_via_ws(payload: dict) -> WritebackResult:
    """方案 B：经 HIS 长连接下发回写（写入 + 刷新），以 ack 的 code 判定成败。

    ack 超时重发由 ws_manager 负责（10s×3，规范 7.4）；耗尽或断线抛 ConnectionError。
    方案 B 凭证只有一套：双向均用 his_inbound_app_id/secret 签名。
    """
    aid, secret = settings.his_inbound_app_id, settings.his_inbound_app_secret

    # 1. 写入（prefer_visit：优先发回该就诊的接诊来源诊室，见 ws_manager 路由规则）
    try:
        ack = await his_ws_manager.send_with_ack(
            wp.MSG_WRITEBACK, payload, aid, secret, prefer_visit=payload["visit_id"])
    except ConnectionError as exc:
        return WritebackResult(ok=False, status="write_failed", message=f"WS 发送失败：{exc}")
    code = ack.get("code", -1)
    if code != 0:
        return WritebackResult(
            ok=False, status="write_failed",
            message=f"HIS 返回 code={code} {ack.get('message', '')}",
        )
    data = ack.get("data") or {}
    his_doc_id = data.get("record_id") or data.get("doc_id") or data.get("id")

    # 2. 刷新（与 HTTP 通道语义一致：写入成功后必须刷新，失败标记 refresh_failed）
    refresh_payload = {
        "visit_id": payload["visit_id"],
        "target": f"{payload['record_type']}_record",
    }
    try:
        rack = await his_ws_manager.send_with_ack(
            wp.MSG_REFRESH, refresh_payload, aid, secret, prefer_visit=payload["visit_id"])
    except ConnectionError as exc:
        return WritebackResult(
            ok=False, status="refresh_failed",
            message=f"刷新 WS 发送失败：{exc}", his_doc_id=his_doc_id,
        )
    if rack.get("code", -1) != 0:
        return WritebackResult(
            ok=False, status="refresh_failed",
            message=f"刷新 HIS 返回 code={rack.get('code')}", his_doc_id=his_doc_id,
        )
    return WritebackResult(ok=True, status="success", his_doc_id=his_doc_id)
