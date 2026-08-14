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
                  （原子计数 + 登录成功后 reset 清零，见 check/reset）
  ai_limiter    : AI 接口，按 IP 限速，30次/分钟，防滥用
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from app.core.client_ip import get_client_ip
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)


class RateLimiter:
    """限流器：Redis 优先，内存版兜底。

    Args:
        max_calls: 时间窗口内允许的最大调用次数。
        window:    时间窗口大小（timedelta）。
        name:      限速器名称，用于 Redis key 前缀，避免不同 limiter 互相干扰。
    """

    # 内存表条目数超过它就顺带扫一次过期项（见 _sweep_expired）。
    # 取值只需远大于正常并发用户数、又不至于让单次清扫太久。
    _SWEEP_THRESHOLD = 512

    def __init__(self, max_calls: int, window: timedelta, *, name: str):
        self.max_calls = max_calls
        self.window = window
        self.name = name
        # key → 该窗口内的调用时间戳列表（仅 Redis 不可用时用）
        self._store: dict[str, list[datetime]] = defaultdict(list)

    def _get_key(self, request: Request, extra: str = "") -> str:
        """从请求中提取限速 key，默认为 "客户端IP:extra"。

        IP 走 get_client_ip 解析 XFF / X-Real-IP，保证反代环境下能按真实用户
        网络维度限速（之前用 request.client.host 拿到的是反代容器内网 IP，
        会让一整个反代后面的所有用户共享一个限速桶 → 单用户爆破耗光所有人额度）。
        """
        ip = get_client_ip(request) or "unknown"
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

    # ── 成功即清零（2026-08-13 第三轮审计修正）─────────────────────────────
    # 原先为了"只计失败"把 check 拆成了 peek(只读判超限) + hit(事后计数)，
    # **丢掉了 INCR 的原子性**：N 个并发请求会同时 peek 到"未超限"然后一起放行，
    # 阈值可按并发数成倍绕过——这是把爆破防护换成了可用性，得不偿失。
    # 现在回到原子 check（每次尝试都 INCR 后判断），只额外提供 reset：
    # 登录成功后清零。效果等价——成功者计数刚+1 就被清回 0，永远攒不到阈值；
    # 而并发失败尝试仍被原子计数卡死在阈值上。
    async def reset(self, key_override: str):
        """清零（如登录成功、管理员重置密码后解锁该用户名）。"""
        await redis_cache.delete(f"ratelimit:{self.name}:{key_override}")
        self._store.pop(key_override, None)

    def _sweep_expired(self, cutoff: datetime) -> None:
        """清掉整段窗口内都没再出现过的 key（2026-08-14 第八轮审计修复）。

        原先清理**只发生在「同一个 key 再次被 check 到」那一行**，此外没有任何
        后台清理或容量上限。ai_limiter / username_check_limiter 的 key 是客户端
        IP：扫描器或 NAT 后的大量不同 IP 各留一个条目后再不回来，条目就永久驻留；
        Redis 恢复后也不会被回收（reset 只删单个 key），只有重启进程才清。
        在 2 核 4G、每 worker 约 200MB 的生产上，这是一条只增不减的内存占用。
        """
        stale = [k for k, times in self._store.items()
                 if not times or times[-1] <= cutoff]
        for k in stale:
            self._store.pop(k, None)

    def _check_in_memory(self, key: str):
        """内存滑动窗口（Redis 不可用时降级使用）。

        ⚠️ 已知局限：生产是 2 个 uvicorn worker，各持一份内存计数，
        降级期间登录爆破的实际阈值翻倍（10 次/10 分钟 → 20 次/10 分钟）——
        而这恰恰是 Redis 出问题、最需要防护的时候。彻底解决要引入进程间共享
        存储，那本来就是 Redis 的职责；这里如实记录，不假装它是准确的。
        """
        now = datetime.now()
        cutoff = now - self.window
        # 每积累一定条目就顺带扫一次过期的，避免只增不减
        if len(self._store) > self._SWEEP_THRESHOLD:
            self._sweep_expired(cutoff)
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

# 用户名查重接口（公开端点，登录页要用）：按 IP 限速
# 2026-06-11 安全加固：无限速时可被脚本批量枚举全院账号（CWE-203），
# 20次/分钟对正常用户（登录页输入时查一次）完全无感，对批量枚举是硬约束
username_check_limiter = RateLimiter(
    max_calls=20, window=timedelta(minutes=1), name="check_username"
)
