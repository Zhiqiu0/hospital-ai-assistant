"""Redis 缓存——数据读写操作（services/_redis_ops.py）

从 redis_cache.py 拆出的数据面方法（RedisCache 的数据 mixin）：
  - get_bytes / set_bytes / delete / delete_prefix ：二进制缓存
  - get_json / set_json                            ：JSON 缓存
  - incr_with_ttl                                  ：带 TTL 计数器（限流用）

行为与原实现完全一致，仅做机械搬迁。所有方法用 self，
依赖门面/核心 mixin 提供的 _get_client / _on_success / _on_failure。
"""
from __future__ import annotations

import json
from typing import Any, Optional


class RedisOpsMixin:
    """bytes / JSON 缓存 + 计数器（供 RedisCache 组合）。"""

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
