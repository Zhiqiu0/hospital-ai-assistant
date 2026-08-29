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


@pytest.mark.asyncio
async def test_dept_admin_cannot_bulk_import_super_admin(api):
    """批量开户不能绕过角色分级造超管（2026-08-13 第三轮审计修复）。

    该端点原先只有 require_admin，而 require_admin 放行到 dept_admin——
    低级管理员传 role="super_admin" 就能造出超管账号，且初始密码由他自己指定，
    登录改密即接管全院，等于把 PR#89 已修的提权洞开了个新入口。
    """
    db, as_user = api
    dept = await _mk_user(db, username="deptbulk", role="dept_admin")
    async with as_user(dept) as ac:
        res = await ac.post("/api/v1/admin/users/bulk-import", json={
            "items": [{"real_name": "假超管", "codes": ["9999"], "role": "super_admin"}],
        })
    assert res.status_code == 403
    # 确认没有偷偷落库
    from sqlalchemy import select
    leaked = (await db.execute(
        select(User).where(User.username == "9999")
    )).scalars().first()
    assert leaked is None


@pytest.mark.asyncio
async def test_bulk_import_rejects_invalid_role(api):
    """脏角色字符串也进不去（assert_can_set_role 内部会校验 VALID_ROLES）。"""
    db, as_user = api
    superu = await _mk_user(db, username="superbulk", role="super_admin")
    async with as_user(superu) as ac:
        res = await ac.post("/api/v1/admin/users/bulk-import", json={
            "items": [{"real_name": "脏角色", "codes": ["8888"], "role": "god_mode"}],
        })
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_dept_admin_cannot_reset_other_department(api):
    """科室管理员不能重置其他科室医生的密码（2026-08-14 第六轮审计修复）。

    原守卫只比角色等级、完全不看科室——dept_admin 实际等于全院管理员。
    而重置密码后那个账号要用管理员知道的临时密码登录，等于跨科室接管账号，
    之后可以以那位医生的名义签发病历。
    """
    db, as_user = api
    dept_a = await _mk_user(db, username="dadmin_a", role="dept_admin")
    dept_a.department_id = "DEPT-A"
    other = await _mk_user(db, username="doc_b", role="doctor")
    other.department_id = "DEPT-B"
    await db.commit()

    async with as_user(dept_a) as ac:
        res = await ac.post(f"/api/v1/admin/users/{other.id}/reset-password",
                            json={"new_password": "Hacked@12345"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_dept_admin_can_manage_own_department(api):
    """本科室的仍可正常管理——不能因为加限制把正常工作堵死。"""
    db, as_user = api
    dept_a = await _mk_user(db, username="dadmin_c", role="dept_admin")
    dept_a.department_id = "DEPT-C"
    mine = await _mk_user(db, username="doc_c", role="doctor")
    mine.department_id = "DEPT-C"
    await db.commit()

    async with as_user(dept_a) as ac:
        res = await ac.post(f"/api/v1/admin/users/{mine.id}/reset-password",
                            json={"new_password": "NewPass@12345"})
    assert res.status_code == 200


# ── #220 update 通道跨科角色守卫回归锁（2026-08-29 第十一轮收敛验证建议）──


async def _mk_dept_user(db, *, username, role, department_id):
    u = User(username=username, password_hash="x", real_name=username,
             role=role, is_active=True, department_id=department_id)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_dept_admin_cannot_promote_to_qc_officer(api):
    """dept_admin 把本科室医生改成 qc_officer（跨科只读权限）必须 403。"""
    db, as_user = api
    dept = await _mk_dept_user(db, username="da1", role="dept_admin", department_id="D1")
    doc = await _mk_dept_user(db, username="dc1", role="doctor", department_id="D1")
    async with as_user(dept) as ac:
        res = await ac.put(f"/api/v1/admin/users/{doc.id}", json={"role": "qc_officer"})
    assert res.status_code == 403, "update 通道的跨科角色授予守卫被改坏"


@pytest.mark.asyncio
async def test_dept_admin_cannot_migrate_department(api):
    """dept_admin 把账号（含自己）迁往他科必须 403——跨科铸号变体。"""
    db, as_user = api
    dept = await _mk_dept_user(db, username="da2", role="dept_admin", department_id="D1")
    async with as_user(dept) as ac:
        res = await ac.put(f"/api/v1/admin/users/{dept.id}", json={"department_id": "D2"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_same_value_role_and_dept_not_blocked(api):
    """同值 role/department_id 提交不误拦（防 != 条件将来被改坏）。"""
    db, as_user = api
    dept = await _mk_dept_user(db, username="da3", role="dept_admin", department_id="D1")
    doc = await _mk_dept_user(db, username="dc3", role="doctor", department_id="D1")
    async with as_user(dept) as ac:
        res = await ac.put(f"/api/v1/admin/users/{doc.id}",
                           json={"role": "doctor", "department_id": "D1",
                                 "real_name": "改名测试"})
    assert res.status_code == 200, res.text
