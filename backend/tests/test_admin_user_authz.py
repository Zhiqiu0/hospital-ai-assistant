"""admin 用户管理分级守卫测试（2026-08-11 审计修复）。

覆盖：dept_admin 不能给超管改密/自提权/停用超管；超管保留守卫；正常路径放行。
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import require_admin
from app.database import get_db
from app.main import app
from app.models.user import User


async def _mk_user(db, *, username, role, is_active=True) -> User:
    u = User(username=username, password_hash="x", real_name=username,
             role=role, is_active=is_active)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def api(async_db):
    """以指定操作者身份发请求的工厂：override get_db + require_admin。"""
    transport = ASGITransport(app=app)

    def _as(operator: User):
        app.dependency_overrides[get_db] = lambda: async_db
        app.dependency_overrides[require_admin] = lambda: operator
        return AsyncClient(transport=transport, base_url="http://test")

    yield async_db, _as
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dept_admin_cannot_reset_super_admin_password(api):
    db, as_user = api
    dept = await _mk_user(db, username="dept1", role="dept_admin")
    superu = await _mk_user(db, username="super1", role="super_admin")
    async with as_user(dept) as ac:
        res = await ac.post(f"/api/v1/admin/users/{superu.id}/reset-password",
                            json={"new_password": "hacked12345"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_dept_admin_cannot_self_promote_to_super(api):
    db, as_user = api
    dept = await _mk_user(db, username="dept2", role="dept_admin")
    async with as_user(dept) as ac:
        res = await ac.put(f"/api/v1/admin/users/{dept.id}",
                           json={"role": "super_admin"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_dept_admin_cannot_create_super_admin(api):
    db, as_user = api
    dept = await _mk_user(db, username="dept3", role="dept_admin")
    async with as_user(dept) as ac:
        res = await ac.post("/api/v1/admin/users", json={
            "username": "evil", "password": "x1234567", "real_name": "e",
            "role": "super_admin",
        })
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_cannot_deactivate_last_super_admin(api):
    db, as_user = api
    superu = await _mk_user(db, username="onlysuper", role="super_admin")
    other = await _mk_user(db, username="super_op", role="super_admin", is_active=False)
    # 操作者是另一个（已停用不影响鉴权 override）超管，但系统仅剩 1 个在用超管
    async with as_user(other) as ac:
        res = await ac.delete(f"/api/v1/admin/users/{superu.id}")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_super_admin_can_reset_doctor_password(api):
    db, as_user = api
    superu = await _mk_user(db, username="super_ok", role="super_admin")
    doc = await _mk_user(db, username="doc_ok", role="doctor")
    async with as_user(superu) as ac:
        res = await ac.post(f"/api/v1/admin/users/{doc.id}/reset-password",
                            json={"new_password": "newpass12345"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
