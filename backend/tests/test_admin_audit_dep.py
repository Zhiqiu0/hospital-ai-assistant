"""管理员审计依赖（core/audit_dep.py）测试

回归保护 S3 修复：以前 admin/* 路由 0 审计，现在挂在 admin 聚合 router 的
路由级 dependency 上，无论端点成功 / 失败都会写一条 audit_logs。

覆盖：
  1. 成功调用一个真实 admin 端点（GET /admin/users）→ audit_logs 多 1 条 status=ok
  2. 端点抛异常（用 dependency_overrides 注入故意抛错的 endpoint）→ status=fail
  3. 调用方非 admin → require_admin 拦截在前，不写 audit（这是预期行为）
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.audit_dep import audit_admin_action
from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.user import User


@pytest_asyncio.fixture
async def admin_user(async_db) -> User:
    user = User(
        id="admin-test-1",
        username="admin_tester",
        password_hash="x",
        real_name="审计测试管理员",
        role="super_admin",
        is_active=True,
    )
    async_db.add(user)
    await async_db.commit()
    return user


@pytest_asyncio.fixture
async def patched_audit_session(async_db, monkeypatch):
    """audit_service 用模块级 AsyncSessionLocal 直连真实库——
    在测试里把它 patch 成"复用当前测试 session"的伪 sessionmaker，
    保证 audit 写入也能在测试断言里读到，且不污染开发/生产数据库。
    """

    @asynccontextmanager
    async def _fake_session_factory():
        # 直接复用测试 fixture 提供的 session，不开新连接、不开新事务
        yield async_db

    # 注意：audit_service 内部用 `async with AsyncSessionLocal() as db: ...`
    # 所以 patch 目标必须是"调用后返回 async context manager"
    monkeypatch.setattr(
        "app.services.audit_service.AsyncSessionLocal",
        _fake_session_factory,
    )
    yield


@pytest_asyncio.fixture
async def client(async_db, admin_user, patched_audit_session) -> AsyncGenerator[AsyncClient, None]:
    """绑定测试 DB session + 跳过真实 token 校验，注入 admin_user。"""
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _count_audit_logs(db) -> int:
    rows = (await db.execute(select(AuditLog))).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_admin_endpoint_success_writes_audit(client, async_db):
    """调用 GET /admin/users 成功 → audit_logs 应多一条 status=ok 记录。"""
    before = await _count_audit_logs(async_db)

    res = await client.get("/api/v1/admin/users")
    assert res.status_code == 200

    # log_action 走独立 session，需要刷新当前 session 才能看到
    await async_db.commit()
    rows = (await async_db.execute(select(AuditLog))).scalars().all()
    assert len(rows) == before + 1

    entry = rows[-1]
    assert entry.action.startswith("admin:GET:/api/v1/admin/users")
    assert entry.user_role == "super_admin"
    assert entry.status == "ok"


@pytest.mark.asyncio
async def test_non_admin_blocked_before_audit(async_db, patched_audit_session):
    """非 admin 角色被 require_admin 在前面拦截 → 不写 audit。"""
    doctor = User(
        id="doc-not-admin",
        username="doc_not_admin",
        password_hash="x",
        real_name="普通医生",
        role="doctor",
        is_active=True,
    )
    async_db.add(doctor)
    await async_db.commit()

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doctor

    transport = ASGITransport(app=app)
    before = await _count_audit_logs(async_db)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/v1/admin/users")
    app.dependency_overrides.clear()

    assert res.status_code == 403
    await async_db.commit()
    after = await _count_audit_logs(async_db)
    assert after == before, "未通过角色校验时不应写审计"


@pytest.mark.asyncio
async def test_audit_dep_records_failure_path(async_db, admin_user, patched_audit_session):
    """端点内部抛异常时 audit 应记 status=fail（yield-finally 路径）。"""
    # 直接调用 dep 函数，构造一个会抛异常的"端点"语义
    from fastapi import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/admin/users",
        "headers": [],
        "query_string": b"",
        "client": ("1.2.3.4", 0),
    }
    req = Request(scope)

    before = await _count_audit_logs(async_db)
    gen = audit_admin_action(request=req, current_user=admin_user)
    user = await gen.__anext__()
    assert user.id == admin_user.id
    # 模拟端点抛异常
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("simulated endpoint failure"))

    await async_db.commit()
    rows = (await async_db.execute(select(AuditLog))).scalars().all()
    assert len(rows) == before + 1
    assert rows[-1].status == "fail"
    assert rows[-1].action == "admin:POST:/api/v1/admin/users"
    assert rows[-1].ip_address == "1.2.3.4"
