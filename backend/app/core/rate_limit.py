"""
轻量内存限流器，无需外部依赖。
适合单进程部署；多进程/多节点部署时请替换为 Redis 后端。
"""
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, max_calls: int, window: timedelta):
        self.max_calls = max_calls
        self.window = window
        self._store: dict[str, list[datetime]] = defaultdict(list)

    def _get_key(self, request: Request, extra: str = "") -> str:
        ip = request.client.host if request.client else "unknown"
        return f"{ip}:{extra}"

    def check(self, request: Request, extra: str = ""):
        key = self._get_key(request, extra)
        now = datetime.now()
        cutoff = now - self.window
        self._store[key] = [t for t in self._store[key] if t > cutoff]
        if len(self._store[key]) >= self.max_calls:
            retry_after = int(self.window.total_seconds())
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 {retry_after // 60} 分钟后重试",
                headers={"Retry-After": str(retry_after)},
            )
        self._store[key].append(now)


# 登录接口：5 次 / 5 分钟（防爆破）
login_limiter = RateLimiter(max_calls=5, window=timedelta(minutes=5))

# AI 接口：30 次 / 分钟（防滥用）
ai_limiter = RateLimiter(max_calls=30, window=timedelta(minutes=1))
