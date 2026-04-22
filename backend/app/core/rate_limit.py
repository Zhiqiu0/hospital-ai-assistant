"""
轻量内存限流器（core/rate_limit.py）

实现原理：
  滑动时间窗口算法。为每个限速 key（IP 或用户名）维护一个时间戳列表，
  每次请求时清除窗口外的旧记录，再判断剩余调用次数。

适用场景：
  单进程部署（Docker 单容器）。
  多进程/多节点部署（K8s 多副本）时，各进程内存独立，
  限流不能跨进程生效，需替换为 Redis 后端（如 slowapi + redis）。

预置实例：
  login_limiter : 登录接口，按用户名限速，10次/10分钟，防密码爆破
  ai_limiter    : AI 接口，按 IP 限速，30次/分钟，防滥用
"""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import HTTPException, Request


class RateLimiter:
    """基于内存的滑动窗口限流器。

    Args:
        max_calls: 时间窗口内允许的最大调用次数。
        window:    时间窗口大小（timedelta）。
    """

    def __init__(self, max_calls: int, window: timedelta):
        self.max_calls = max_calls
        self.window = window
        # key → 该窗口内的调用时间戳列表
        self._store: dict[str, list[datetime]] = defaultdict(list)

    def _get_key(self, request: Request, extra: str = "") -> str:
        """从请求中提取限速 key，默认为 "客户端IP:extra"。

        Args:
            request: FastAPI 请求对象，用于获取客户端 IP。
            extra:   附加区分字符串，如端点名称，避免不同接口互相干扰。
        """
        ip = request.client.host if request.client else "unknown"
        return f"{ip}:{extra}"

    def check(self, request: Request, extra: str = "", key_override: str = ""):
        """检查是否超出限速阈值，超出则抛出 429 异常。

        Args:
            request:      FastAPI 请求对象（用于提取 IP）。
            extra:        key 后缀，用于区分不同接口（默认按 IP 全局限速）。
            key_override: 非空时直接用此值作为限速 key（如按用户名限速时传入用户名）。

        Raises:
            HTTPException(429): 超出限速阈值，响应头携带 Retry-After。
        """
        key = key_override if key_override else self._get_key(request, extra)
        now = datetime.now()
        cutoff = now - self.window

        # 滑动窗口：清除窗口外的旧时间戳
        self._store[key] = [t for t in self._store[key] if t > cutoff]

        if len(self._store[key]) >= self.max_calls:
            retry_after = int(self.window.total_seconds())
            raise HTTPException(
                status_code=429,
                detail=f"登录失败次数过多，请 {retry_after // 60} 分钟后重试",
                headers={"Retry-After": str(retry_after)},
            )

        # 记录本次调用时间戳
        self._store[key].append(now)


# ── 预置限流实例 ──────────────────────────────────────────────────────────────

# 登录接口：按用户名限速（不按 IP，避免同院 NAT 下多用户互相干扰）
# 10次/10分钟，给医生足够的容错空间
login_limiter = RateLimiter(max_calls=10, window=timedelta(minutes=10))

# AI 功能接口（生成/质控/润色等）：按 IP 限速
# 30次/分钟，防止单用户高频调用消耗大量 LLM token
ai_limiter = RateLimiter(max_calls=30, window=timedelta(minutes=1))
