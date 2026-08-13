"""登录限流「只计失败」行为测试（2026-08-13）。

背景：原先 check() 在鉴权前无条件计数，成功登录也占额度——医生 10 分钟内成功
登录超过 10 次，第 11 次密码正确也被 429。限流要挡的是"猜密码"，猜对的那次
不该算。改为 peek/hit/reset 后本文件锁住三条行为：
  1. 连续成功登录不会把自己锁死
  2. 连续失败仍在同一阈值上被拦（爆破防护没被削弱）
  3. 失败几次后登录成功 → 计数清零，额度恢复
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from datetime import timedelta

from app.core.rate_limit import login_limiter
from app.core.security import hash_password
from app.database import get_db
from app.main import app
from app.models.user import User

PWD = "RateLimit@123"


@pytest_asyncio.fixture
async def api(async_db, monkeypatch):
    """建一个可登录的医生 + 干净的限流状态。"""
    user = User(username="ratelimitdoc", password_hash=hash_password(PWD),
                real_name="限流测试医生", role="doctor", is_active=True)
    async_db.add(user)
    await async_db.commit()

    # 审计日志写独立会话，测试里指回内存库
    import app.services.audit_service as audit_service

    class _Ctx:
        async def __aenter__(self):
            return async_db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(audit_service, "AsyncSessionLocal", lambda: _Ctx())

    await login_limiter.reset("login:ratelimitdoc")
    app.dependency_overrides[get_db] = lambda: async_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await login_limiter.reset("login:ratelimitdoc")


async def _login(ac: AsyncClient, password: str):
    return await ac.post("/api/v1/auth/login",
                         json={"username": "ratelimitdoc", "password": password})


@pytest.mark.asyncio
async def test_repeated_successful_logins_never_locked(api):
    """连续成功登录远超阈值也不被锁——医生不该被自己的正常使用锁在门外。"""
    for i in range(login_limiter.max_calls + 5):
        r = await _login(api, PWD)
        assert r.status_code == 200, f"第 {i + 1} 次成功登录被拦：{r.status_code}"


@pytest.mark.asyncio
async def test_repeated_failures_still_blocked(api):
    """连续失败仍在阈值处被 429——爆破防护没被削弱。"""
    for _ in range(login_limiter.max_calls):
        r = await _login(api, "WrongPassword")
        assert r.status_code == 401
    r = await _login(api, "WrongPassword")
    assert r.status_code == 429
    # 已锁定时即便密码正确也进不去（这是限流的应有之义）
    assert (await _login(api, PWD)).status_code == 429


@pytest.mark.asyncio
async def test_success_resets_failure_counter(api):
    """手滑输错几次后输对 → 计数清零，额度恢复满。"""
    for _ in range(login_limiter.max_calls - 1):
        assert (await _login(api, "WrongPassword")).status_code == 401
    assert (await _login(api, PWD)).status_code == 200

    # 若没清零，这里第一次失败就会撞上阈值
    for _ in range(login_limiter.max_calls - 1):
        assert (await _login(api, "WrongPassword")).status_code == 401


@pytest.mark.asyncio
async def test_concurrent_checks_cannot_exceed_threshold():
    """并发计数不能突破阈值（2026-08-13 第三轮审计修复的回归锁）。

    曾经为了「只计失败」把 check 拆成 peek(只读判超限) + hit(事后计数)，
    丢掉了 INCR 的原子性：N 个并发请求同时 peek 到"未超限"然后一起放行，
    阈值可按并发数成倍绕过。现在回到原子 check + 登录成功后 reset。

    直接测限流器本身而不走登录接口：并发打同一个 HTTP 端点会让测试里共享的
    AsyncSession 并发使用而报错，那是测试夹具的限制，与被测性质无关。
    """
    import asyncio

    from fastapi import HTTPException

    from app.core.rate_limit import RateLimiter

    limiter = RateLimiter(max_calls=10, window=timedelta(minutes=10), name="concur_test")
    key = "concur:case1"
    await limiter.reset(key)

    async def one():
        try:
            await limiter.check(None, key_override=key)
            return True          # 放行
        except HTTPException:
            return False         # 被拦

    passed = sum(await asyncio.gather(*[one() for _ in range(limiter.max_calls * 3)]))
    await limiter.reset(key)

    assert passed <= limiter.max_calls, (
        f"并发下放行了 {passed} 次，超过阈值 {limiter.max_calls}——原子性又丢了"
    )
    assert passed > 0, "一次都没放行，限流器坏了"
