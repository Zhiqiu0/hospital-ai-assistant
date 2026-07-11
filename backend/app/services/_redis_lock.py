"""Redis 缓存——分布式锁与 nonce（services/_redis_lock.py）

从 redis_cache.py 拆出的锁面方法（RedisCache 的锁 mixin）：
  - acquire_lock / release_lock ：分布式幂等锁（防双击建两条 / AI 重复触发）
  - claim_nonce                 ：一次性 nonce 声明（防重放）

行为与原实现完全一致，仅做机械搬迁。所有方法用 self，
依赖门面/核心 mixin 提供的 _get_client / _on_success / _on_failure。
"""
from __future__ import annotations

import uuid
from typing import Optional


class RedisLockMixin:
    """分布式锁 + 一次性 nonce（供 RedisCache 组合）。"""

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

    async def claim_nonce(self, scope: str, nonce: str, *, ttl: int) -> bool:
        """一次性 nonce 声明（防重放）。

        用 SET NX EX 把 nonce 记为「已用」：首次声明返回 True（放行），
        再次声明返回 False（判定为重放，应拒绝）。

        Args:
            scope: 命名空间（如 "his_admit"），避免不同业务 nonce 撞车。
            nonce: 外部传入的一次性随机串。
            ttl:   记忆时长（秒），应 >= 验签允许的时间戳偏差窗口——
                   超过窗口后 timestamp_fresh 本身就会拒绝，nonce 无需再记。

        Returns:
            True  = nonce 首次出现（放行）；
            False = nonce 已用过（重放，拒绝）。
            Redis 不可用时返回 True（fail-open，与本模块降级哲学一致）：
            此时防重放退化为仅靠时间戳窗口兜底，属已知取舍。
        """
        if not nonce:
            # 没带 nonce 交给上层的签名/参数校验去拒，这里不放行也不误判
            return False
        client = self._get_client()
        if client is None:
            return True
        try:
            ok = await client.set(f"nonce:{scope}:{nonce}", "1", nx=True, ex=ttl)
            self._on_success()
            return bool(ok)
        except Exception as e:
            self._on_failure("claim_nonce", f"{scope}:{nonce}", e)
            return True
