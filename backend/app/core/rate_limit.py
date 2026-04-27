"""
限流器（core/rate_limit.py）

实现：
  - 优先走 Redis 固定窗口（INCR + EXPIRE），跨进程跨副本一致
  - Redis 不可用时降级到内存滑动窗口，单容器仍可用

固定窗口 vs 滑动窗口：
  Redis 路径用固定窗口（首次 INCR 同时 SET TTL，到期自动清零），实现简单且
  原子；最差情况下短时窗口边界可能放过 2*max_calls 次调用，但对登录爆破/
  AI 滥用这种粗粒度防护够用。

预置实例：
  login_limiter : 登录接口，按用户名限速，10次/10分钟，防密码爆破
  ai_limiter    : AI 接口，按 IP 限速，30次/分钟，防滥用
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)


class RateLimiter:
    """限流器：Redis 优先，内存版兜底。

    Args:
        max_calls: 时间窗口内允许的最大调用次数。
        window:    时间窗口大小（timedelta）。
        name:      限速器名称，用于 Redis key 前缀，避免不同 limiter 互相干扰。
    """

    def __init__(self, max_calls: int, window: timedelta, *, name: str):
        self.max_calls = max_calls
        self.window = window
        self.name = name
        # key → 该窗口内的调用时间戳列表（仅 Redis 不可用时用）
        self._store: dict[str, list[datetime]] = defaultdict(list)

    def _get_key(self, request: Request, extra: str = "") -> str:
        """从请求中提取限速 key，默认为 "客户端IP:extra"。"""
        ip = request.client.host if request.client else "unknown"
        return f"{ip}:{extra}"

    async def check(self, request: Request, extra: str = "", key_override: str = ""):
        """检查是否超出限速阈值，超出则抛出 429 异常。

        Args:
            request:      FastAPI 请求对象（用于提取 IP）。
            extra:        key 后缀，用于区分不同接口（默认按 IP 全局限速）。
            key_override: 非空时直接用此值作为限速 key（如按用户名限速时传入用户名）。

        Raises:
            HTTPException(429): 超出限速阈值，响应头携带 Retry-After。
        """
        key = key_override if key_override else self._get_key(request, extra)
        window_seconds = int(self.window.total_seconds())

        # ① 优先走 Redis：跨进程一致，多副本部署也能正确限流
        redis_key = f"ratelimit:{self.name}:{key}"
        count = await redis_cache.incr_with_ttl(redis_key, window_seconds=window_seconds)
        if count is not None:
            if count > self.max_calls:
                self._raise_429(window_seconds)
            return  # Redis 路径成功，不再走内存

        # ② Redis 不可用，降级到本进程内存版（单容器场景）
        self._check_in_memory(key)

    def _check_in_memory(self, key: str):
        """内存滑动窗口（Redis 不可用时降级使用）。"""
        now = datetime.now()
        cutoff = now - self.window
        self._store[key] = [t for t in self._store[key] if t > cutoff]
        if len(self._store[key]) >= self.max_calls:
            self._raise_429(int(self.window.total_seconds()))
        self._store[key].append(now)

    def _raise_429(self, retry_after: int):
        # 业务里程碑：限流触发（暴破登录预警靠这条；用 warning 让 Sentry 也能聚合）
        # name 区分 limiter 类型（login / ai 等），retry_after 标识窗口
        logger.warning(
            "rate_limit.blocked: limiter=%s retry_after=%ds (max=%d window=%ds)",
            self.name, retry_after, self.max_calls, retry_after,
        )
        raise HTTPException(
            status_code=429,
            detail=f"操作过于频繁，请 {retry_after // 60} 分钟后重试" if retry_after >= 60
                   else f"操作过于频繁，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )


# ── 预置限流实例 ──────────────────────────────────────────────────────────────

# 登录接口：按用户名限速（不按 IP，避免同院 NAT 下多用户互相干扰）
# 10次/10分钟，给医生足够的容错空间
login_limiter = RateLimiter(max_calls=10, window=timedelta(minutes=10), name="login")

# AI 功能接口（生成/质控/润色等）：按 IP 限速
# 30次/分钟，防止单用户高频调用消耗大量 LLM token
ai_limiter = RateLimiter(max_calls=30, window=timedelta(minutes=1), name="ai")
