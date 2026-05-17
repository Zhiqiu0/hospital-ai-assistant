"""
auth.logout 幂等性测试（test_auth_logout_idempotent.py）

防回归点：
  1. 同一 token 第二次 logout 不返回 500（业内 bug：jti 重复 insert 触发 UNIQUE）
  2. Redis 写失败不阻断主流程（DB 是黑名单权威源）
  3. 无 token / 无效 token 直接返回 ok（路由级幂等）

复现 bug 历史：
  用户截图显示 /auth/logout 500 → "duplicate key violates revoked_tokens_pkey"
  根因：连点退出 / 并发请求第二个到达时 jti 已在表里 → IntegrityError → 500
  治本：在 INSERT 失败时 rollback + 视为成功（目标状态"token 已失效"已达成）
"""
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.api.v1.auth import logout
from app.config import settings
from app.models.revoked_token import RevokedToken


def _make_token(jti: str = "test-jti-12345", expires_in_sec: int = 3600) -> str:
    """造一个合法的测试 JWT。"""
    payload = {
        "sub": "test-user-id",
        "jti": jti,
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=expires_in_sec)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


@pytest.mark.asyncio
async def test_logout_first_call_success(async_db):
    """首次 logout：jti 写入黑名单，返回 ok=True。"""
    token = _make_token(jti="first-call-jti")
    result = await logout(token=token, db=async_db)
    assert result == {"ok": True}

    # 验证 DB 真的写进去了
    from sqlalchemy import select
    rows = (await async_db.execute(select(RevokedToken).where(RevokedToken.jti == "first-call-jti"))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_logout_second_call_same_jti_is_idempotent(async_db, monkeypatch):
    """治本核心：同一 token 重复 logout 不报 500，幂等返回 ok=True。

    复现路径：用户连点退出 / 并发 logout / 多 tab 同 token 都会触发。
    旧实现：第二次 INSERT 触发 UniqueViolationError → 500
    新实现：catch IntegrityError → rollback → 视为成功
    """
    token = _make_token(jti="repeat-jti")
    # 第一次：正常写入
    result1 = await logout(token=token, db=async_db)
    assert result1 == {"ok": True}

    # 第二次：jti 已存在，应该幂等成功而非 500
    result2 = await logout(token=token, db=async_db)
    assert result2 == {"ok": True}

    # DB 里仍然只有一条记录（不重复）
    from sqlalchemy import select, func
    count = (await async_db.execute(
        select(func.count()).select_from(RevokedToken).where(RevokedToken.jti == "repeat-jti")
    )).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_logout_redis_failure_does_not_block(async_db, monkeypatch):
    """Redis 写失败时主流程仍成功（DB 是黑名单权威源，Redis 只是热路径）。

    历史 bug 日志可见 "Timeout connecting to server" 紧跟 redis.op: failed，
    必须确保这种环境下 logout 仍返回 200。
    """
    from app.services import redis_cache as rc_module

    async def failing_set_bytes(*args, **kwargs):
        raise ConnectionError("Redis timeout")

    monkeypatch.setattr(rc_module.redis_cache, "set_bytes", failing_set_bytes)

    token = _make_token(jti="redis-fail-jti")
    result = await logout(token=token, db=async_db)
    assert result == {"ok": True}

    # DB 写入仍成功
    from sqlalchemy import select
    rows = (await async_db.execute(select(RevokedToken).where(RevokedToken.jti == "redis-fail-jti"))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_logout_no_token_returns_ok(async_db):
    """无 token（前端已先清 token 再调，或 cookie 被清）→ 直接 ok，不报错。"""
    result = await logout(token=None, db=async_db)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_logout_invalid_token_returns_ok(async_db):
    """token 格式错误 / 签名不对 → JWTError 被吞，返回 ok（避免暴露内部状态）。"""
    result = await logout(token="not.a.valid.jwt", db=async_db)
    assert result == {"ok": True}
