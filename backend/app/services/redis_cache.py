"""Redis 缓存封装（services/redis_cache.py）

定位：通用 Redis 客户端（缓存 + 锁 + 计数），PACS 缩略图首个用例，
后续被 token 黑名单 / AI 配置 / 工作台快照 / 限流 / 幂等锁 等共用。

设计原则：
  - 单例 client，进程内复用 connection pool（async redis-py 5.x）
  - lazy init：第一次用才连，没起 Redis 也不会让 import 阶段炸
  - 失败降级：Redis 不通 / 超时时返回 None / False，调用方按"未命中"处理
  - 不抛异常：缓存层失败不应阻断业务

提供的能力：
  - get_bytes / set_bytes      ：二进制缓存（PACS 影像用）
  - get_json / set_json        ：JSON 缓存（snapshot / profile / 配置等结构化数据用）
  - delete / delete_prefix     ：失效缓存
  - acquire_lock / release_lock：分布式幂等锁（防双击建两条 / AI 重复触发）
  - incr_with_ttl              ：带 TTL 的计数器（限流 / 登录爆破计数用）

用法示例：
    from app.services.redis_cache import redis_cache

    # bytes 缓存（PACS 缩略图）
    data = await redis_cache.get_bytes("pacs:thumb:study1:inst1")

    # JSON 缓存（patient profile）
    profile = await redis_cache.get_json("patient:profile:abc")
    if profile is None:
        profile = await load_from_db()
        await redis_cache.set_json("patient:profile:abc", profile, ttl=300)

    # 幂等锁（quick-start 防双击）
    token = await redis_cache.acquire_lock("lock:quickstart:doc:pat", ttl=5)
    if not token:
        raise HTTPException(409, "请勿重复操作")
    try:
        ...
    finally:
        await redis_cache.release_lock("lock:quickstart:doc:pat", token)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# 熔断参数：连续失败 _BREAKER_THRESHOLD 次 → 进入 _BREAKER_COOLDOWN 秒冷却
# 冷却期内所有请求直接 fallback 不再尝试连 Redis，避免每个请求白等 2 秒。
# 冷却结束后会自动放行一次"试探"请求，成功就重置失败计数恢复正常。
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN = 30


class RedisCache:
    """Redis 缓存客户端（异步 + 失败降级 + 熔断）。

    所有方法在 Redis 不可用（连接失败 / 超时 / 配置缺失）时返回安全默认值，
    调用方可以无脑用：失败时等价于"未命中"，自然 fallback 到原慢路径。

    熔断机制：
      Redis 运行中突然掉线（容器重启、网络抖动）时，每个请求都会等满
      socket_timeout（2s）才降级，整体响应时间骤升。本类用简化版熔断器：
      连续失败 3 次 → 标记 30s 冷却 → 期间所有方法直接 fallback；
      冷却结束后自动尝试一次，成功则恢复，失败则继续冷却。
    """

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None
        # 永久禁用：配置缺失（settings.redis_url 为空）才会置 True，配置改了需重启
        self._unavailable: bool = False
        # 熔断状态
        self._consecutive_failures: int = 0
        # 冷却到期时间戳（unix 秒）；None 表示当前不在冷却
        self._cooldown_until: Optional[float] = None

    def _on_success(self) -> None:
        """任意 Redis 操作成功后调用：重置失败计数，结束冷却。"""
        if self._consecutive_failures or self._cooldown_until:
            logger.info("redis.recover: ok after_failures=%d", self._consecutive_failures)
        self._consecutive_failures = 0
        self._cooldown_until = None

    def _on_failure(self, op: str, key: str, err: Exception) -> None:
        """任意 Redis 操作失败后调用：累计失败次数，达阈值进入冷却。"""
        logger.warning("redis.op: failed op=%s key=%s err=%s", op, key, err)
        self._consecutive_failures += 1
        if (
            self._consecutive_failures >= _BREAKER_THRESHOLD
            and self._cooldown_until is None
        ):
            self._cooldown_until = time.time() + _BREAKER_COOLDOWN
            logger.warning(
                "redis.circuit: open failures=%d cooldown=%ds (requests will fallback)",
                self._consecutive_failures, _BREAKER_COOLDOWN,
            )

    def _get_client(self) -> Optional[aioredis.Redis]:
        """lazy 拿 client。配置缺失或熔断冷却中返回 None 让上层降级。"""
        if self._unavailable:
            return None
        # 熔断冷却中：直接 fallback，不再尝试连 Redis（避免每请求等 socket_timeout）
        if self._cooldown_until is not None:
            if time.time() < self._cooldown_until:
                return None
            # 冷却到期：放行一次试探。失败计数先不清，靠 _on_success/_on_failure 来更新
            logger.info("redis.circuit: cooldown_end probing")
            self._cooldown_until = None
        if self._client is None:
            if not settings.redis_url:
                self._unavailable = True
                logger.warning("Redis 未配置 (settings.redis_url 为空)，缓存禁用")
                return None
            try:
                # decode_responses=False：缩略图是 bytes，不要让 redis 强转 str
                self._client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=False,
                    socket_connect_timeout=2.0,  # 连接超时 2s，防止启动阶段挂太久
                    socket_timeout=2.0,
                )
            except Exception as e:
                logger.warning("Redis 初始化失败，缓存禁用: %s", e)
                self._unavailable = True
                return None
        return self._client

    async def get_bytes(self, key: str) -> Optional[bytes]:
        """读 bytes，未命中或 Redis 不可用返回 None。"""
        client = self._get_client()
        if client is None:
            return None
        try:
            result = await client.get(key)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure("GET", key, e)
            return None

    async def set_bytes(self, key: str, value: bytes, *, ttl: Optional[int] = None) -> bool:
        """写 bytes 带可选 TTL。失败返 False（业务方继续，不阻塞）。"""
        client = self._get_client()
        if client is None:
            return False
        try:
            await client.set(key, value, ex=ttl)
            self._on_success()
            return True
        except Exception as e:
            self._on_failure("SET", key, e)
            return False

    async def delete(self, *keys: str) -> int:
        """批量删 key，返回删除数。"""
        if not keys:
            return 0
        client = self._get_client()
        if client is None:
            return 0
        try:
            n = await client.delete(*keys)
            self._on_success()
            return n
        except Exception as e:
            self._on_failure("DEL", ",".join(keys[:3]), e)
            return 0

    async def delete_prefix(self, prefix: str) -> int:
        """删除某前缀下所有 key（用于失效一个 study 的全部缩略图）。

        用 SCAN 而非 KEYS 避免阻塞 Redis（大库下 KEYS 会卡住整个 server）。
        """
        client = self._get_client()
        if client is None:
            return 0
        try:
            cursor = 0
            total = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=f"{prefix}*", count=200)
                if keys:
                    total += await client.delete(*keys)
                if cursor == 0:
                    break
            self._on_success()
            return total
        except Exception as e:
            self._on_failure("SCAN/DEL", prefix, e)
            return 0

    # ── JSON 缓存（结构化数据用：profile / snapshot / 配置等）──────────────────
    async def get_json(self, key: str) -> Optional[Any]:
        """读 JSON，未命中或 Redis 不可用返回 None。

        失败原因（连接异常 / 解码异常）一律降级为 None，由调用方走原慢路径。
        """
        client = self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            self._on_success()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            self._on_failure("GET JSON", key, e)
            return None

    async def set_json(self, key: str, value: Any, *, ttl: Optional[int] = None) -> bool:
        """写 JSON 带可选 TTL；不可序列化对象（datetime/UUID 等）走 default=str 兜底。"""
        client = self._get_client()
        if client is None:
            return False
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
            await client.set(key, payload, ex=ttl)
            self._on_success()
            return True
        except Exception as e:
            self._on_failure("SET JSON", key, e)
            return False

    # ── 分布式锁（幂等 / 防重复触发）────────────────────────────────────────────
    async def acquire_lock(self, key: str, *, ttl: int = 5) -> Optional[str]:
        """SET NX EX 抢锁。

        Returns:
            抢到则返回随机 token（释放时校验所有权，避免误删别人的锁），
            没抢到 / Redis 不可用返回 None。

        Args:
            ttl: 锁自动过期秒数，必须 >0。设短一点（5~60s），
                 防止持锁方崩溃后锁一直占着。
        """
        client = self._get_client()
        if client is None:
            # Redis 不可用时返回伪 token "fallback"，让业务继续走（不锁）；
            # 单容器场景没有 Redis 也不阻断，多副本场景应当确保 Redis 可用
            return "fallback"
        try:
            token = uuid.uuid4().hex
            ok = await client.set(key, token, nx=True, ex=ttl)
            self._on_success()
            return token if ok else None
        except Exception as e:
            self._on_failure("acquire_lock", key, e)
            return "fallback"

    async def release_lock(self, key: str, token: str) -> bool:
        """释放锁。仅当 key 当前值等于 token 才删（防误删别人续上的锁）。

        Lua 脚本保证「比较 + 删除」原子性。
        """
        if token == "fallback":
            return True
        client = self._get_client()
        if client is None:
            return True
        try:
            # KEYS[1]=lock_key，ARGV[1]=token
            script = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end"
            )
            await client.eval(script, 1, key, token)
            self._on_success()
            return True
        except Exception as e:
            self._on_failure("release_lock", key, e)
            return False

    # ── 限流 / 计数器 ────────────────────────────────────────────────────────────
    async def incr_with_ttl(self, key: str, *, window_seconds: int) -> Optional[int]:
        """INCR + 首次 EXPIRE，用于固定窗口限流 / 登录爆破计数。

        Returns:
            INCR 后的当前计数；Redis 不可用时返回 None（调用方决定 fail-open 还是 fail-closed）。

        典型用法（限流）：
            count = await redis_cache.incr_with_ttl("rl:login:alice", window_seconds=600)
            if count is not None and count > 10:
                raise HTTPException(429, ...)
        """
        client = self._get_client()
        if client is None:
            return None
        try:
            # pipeline 保证 INCR 与 EXPIRE 原子（避免第一次 INCR 后未 EXPIRE 进程崩溃，留下永久 key）
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, window_seconds)
                results = await pipe.execute()
            self._on_success()
            return int(results[0]) if results else None
        except Exception as e:
            self._on_failure("INCR", key, e)
            return None

    async def health_check(self) -> bool:
        """ping 一下，调试 / 启动检查用。"""
        client = self._get_client()
        if client is None:
            return False
        try:
            return await client.ping()
        except Exception as exc:
            # health_check 失败用 debug 级（启动探活时偶发，不应进 error.log）
            # 业务路径上的 Redis 失败由 _on_failure 单独记录
            logger.debug("redis.health: failed err=%s", exc)
            return False

    async def close(self):
        """FastAPI lifespan shutdown 时调，干净关 connection pool。"""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                # 关闭失败也不阻断 shutdown，但留个 debug 痕迹
                logger.debug("redis.close: failed err=%s", exc)
            self._client = None


# 全局单例（FastAPI dependency 直接 import 用）
redis_cache = RedisCache()
