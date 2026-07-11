"""Redis 缓存——连接与熔断核心（services/_redis_core.py）

从 redis_cache.py 拆出的连接管理 + 熔断器逻辑（RedisCache 的核心 mixin）。
拆分（超标文件拆分：364 行 → 门面 + 3 mixin）：本 mixin 负责 lazy 建连、
熔断状态机（_on_success / _on_failure / _get_client）。

行为与原实现完全一致，仅做机械搬迁。所有方法用 self，
由门面 RedisCache 组合并在 __init__ 里初始化熔断状态。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# 熔断参数：连续失败 _BREAKER_THRESHOLD 次 → 进入 _BREAKER_COOLDOWN 秒冷却
# 冷却期内所有请求直接 fallback 不再尝试连 Redis，避免每个请求白等 2 秒。
# 冷却结束后会自动放行一次"试探"请求，成功就重置失败计数恢复正常。
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN = 30


class RedisCoreMixin:
    """连接管理 + 熔断状态机（供 RedisCache 组合）。"""

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
