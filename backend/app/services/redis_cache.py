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
  - claim_nonce                ：一次性 nonce 声明（防重放）
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

拆分（超标文件拆分：364 行 → 本门面 + 3 mixin）：
  - _redis_core.RedisCoreMixin ：lazy 建连 + 熔断状态机
  - _redis_ops.RedisOpsMixin   ：bytes / JSON 缓存 + 计数器
  - _redis_lock.RedisLockMixin ：分布式锁 + nonce
兼容：单例 `redis_cache` 与其全部方法保持不变，
      `from app.services.redis_cache import redis_cache` 用法照旧。
"""
from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as aioredis

from app.services._redis_core import RedisCoreMixin
from app.services._redis_lock import RedisLockMixin
from app.services._redis_ops import RedisOpsMixin

logger = logging.getLogger(__name__)


class RedisCache(RedisCoreMixin, RedisOpsMixin, RedisLockMixin):
    """Redis 缓存客户端（异步 + 失败降级 + 熔断）。

    所有方法在 Redis 不可用（连接失败 / 超时 / 配置缺失）时返回安全默认值，
    调用方可以无脑用：失败时等价于"未命中"，自然 fallback 到原慢路径。

    熔断机制：
      Redis 运行中突然掉线（容器重启、网络抖动）时，每个请求都会等满
      socket_timeout（2s）才降级，整体响应时间骤升。本类用简化版熔断器：
      连续失败 3 次 → 标记 30s 冷却 → 期间所有方法直接 fallback；
      冷却结束后自动尝试一次，成功则恢复，失败则继续冷却。

    具体方法实现分布在上面 3 个 mixin 中，本类只负责组合 + 持有连接与熔断状态。
    """

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None
        # 永久禁用：配置缺失（settings.redis_url 为空）才会置 True，配置改了需重启
        self._unavailable: bool = False
        # 熔断状态
        self._consecutive_failures: int = 0
        # 冷却到期时间戳（unix 秒）；None 表示当前不在冷却
        self._cooldown_until: Optional[float] = None

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
