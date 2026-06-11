"""
科室服务单元测试（app/services/department_service.py）

覆盖范围：
  - create / get_by_id 主路径 + 不存在返回 None
  - create 重名 code 触发数据库 UNIQUE 约束（IntegrityError 由路由层兜底）
  - list_all 默认只返回启用科室；include_inactive=True 返回全部
  - list_all 缓存命中路径（get_json 命中时直接返回缓存，不查库）
  - update：改名、显式置 parent_id=None"提升为顶级"、未传 parent_id 时保持原值、404
  - deactivate / activate 软删除往返 + 404

工程注意：
  redis_cache 是模块级单例；本地常开 Redis 时 list_all 会真写
  "department:list_active" 缓存，跨用例互相污染。所以 autouse fixture
  把 Redis 操作 patch 成 no-op，强制全部走 DB（与 snapshot 测试同款做法）。
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.schemas.department import DepartmentCreate, DepartmentUpdate
from app.services.department_service import DepartmentService


@pytest.fixture(autouse=True)
def disable_redis_cache(monkeypatch):
    """所有科室测试强制走 DB，避免本地 Redis 缓存污染。"""
    from app.services.redis_cache import redis_cache

    async def _miss(*_args, **_kwargs):
        return None

    async def _noop(*_args, **_kwargs):
        return True

    async def _noop_int(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(redis_cache, "get_json", _miss)
    monkeypatch.setattr(redis_cache, "set_json", _noop)
    monkeypatch.setattr(redis_cache, "delete", _noop_int)


@pytest_asyncio.fixture
async def svc(async_db):
    """每个用例独享的 DepartmentService 实例。"""
    return DepartmentService(async_db)


# ── create / get_by_id ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_department(svc):
    """新建科室：返回 ORM 对象，默认启用（is_active=True）。"""
    dept = await svc.create(DepartmentCreate(name="心内科", code="cardiology"))
    assert dept.id  # UUID 已生成
    assert dept.name == "心内科"
    assert dept.code == "cardiology"
    assert dept.parent_id is None
    assert dept.is_active is True


@pytest.mark.asyncio
async def test_create_child_department(svc):
    """新建子科室：parent_id 正确落库（科室树场景）。"""
    parent = await svc.create(DepartmentCreate(name="外科", code="surgery"))
    child = await svc.create(
        DepartmentCreate(name="骨科", code="orthopedics", parent_id=parent.id)
    )
    assert child.parent_id == parent.id


@pytest.mark.asyncio
async def test_get_by_id_found_and_missing(svc):
    """get_by_id：存在返回对象，不存在返回 None（不抛异常，由调用方决定 404）。"""
    dept = await svc.create(DepartmentCreate(name="急诊科", code="emergency"))
    found = await svc.get_by_id(dept.id)
    assert found is not None and found.name == "急诊科"
    assert await svc.get_by_id("no-such-id") is None


@pytest.mark.asyncio
async def test_create_duplicate_code_raises(svc, async_db):
    """code 重复触发数据库 UNIQUE 约束 → IntegrityError（路由层负责转友好提示）。"""
    await svc.create(DepartmentCreate(name="儿科", code="pediatrics"))
    with pytest.raises(IntegrityError):
        await svc.create(DepartmentCreate(name="儿科二病区", code="pediatrics"))
    # 清理失败事务，避免影响 fixture 收尾
    await async_db.rollback()


# ── list_all ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_all_active_only_by_default(svc):
    """默认列表只含启用科室；停用的被过滤掉。"""
    a = await svc.create(DepartmentCreate(name="内科", code="internal"))
    b = await svc.create(DepartmentCreate(name="老病区", code="legacy"))
    await svc.deactivate(b.id)

    data = await svc.list_all()
    codes = [item["code"] for item in data["items"]]
    assert "internal" in codes
    assert "legacy" not in codes
    # 返回字段完整（前端组树依赖 parent_id / is_active）
    item = next(i for i in data["items"] if i["id"] == a.id)
    assert set(item.keys()) == {"id", "name", "code", "parent_id", "is_active"}


@pytest.mark.asyncio
async def test_list_all_include_inactive(svc):
    """include_inactive=True：停用科室也返回（后台管理页用），is_active 标记正确。"""
    b = await svc.create(DepartmentCreate(name="停用科", code="disabled"))
    await svc.deactivate(b.id)

    data = await svc.list_all(include_inactive=True)
    item = next(i for i in data["items"] if i["code"] == "disabled")
    assert item["is_active"] is False


@pytest.mark.asyncio
async def test_list_all_cache_hit_short_circuits(svc, monkeypatch):
    """缓存命中时直接返回缓存内容，不再查库（验证热路径走 Redis）。"""
    from app.services.redis_cache import redis_cache

    sentinel = {"items": [{"id": "cached", "name": "缓存科", "code": "c",
                           "parent_id": None, "is_active": True}]}

    async def _hit(_key):
        return sentinel

    monkeypatch.setattr(redis_cache, "get_json", _hit)
    assert await svc.list_all() is sentinel
    # include_inactive=True 不走缓存：即使缓存"命中"也应查库（返回真实空库）
    data = await svc.list_all(include_inactive=True)
    assert data["items"] == []


# ── update ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_rename(svc):
    """改名生效；未传的 parent_id 保持原值（model_fields_set 语义）。"""
    parent = await svc.create(DepartmentCreate(name="外科", code="surg2"))
    child = await svc.create(
        DepartmentCreate(name="普外", code="general-surg", parent_id=parent.id)
    )
    updated = await svc.update(child.id, DepartmentUpdate(name="普通外科"))
    assert updated.name == "普通外科"
    assert updated.parent_id == parent.id  # 没显式传 parent_id → 不动


@pytest.mark.asyncio
async def test_update_parent_id_explicit_none_promotes(svc):
    """显式传 parent_id=None："提升为顶级科室"（区别于不传）。"""
    parent = await svc.create(DepartmentCreate(name="内科", code="int2"))
    child = await svc.create(
        DepartmentCreate(name="心内", code="cardio2", parent_id=parent.id)
    )
    updated = await svc.update(child.id, DepartmentUpdate(parent_id=None))
    assert updated.parent_id is None


@pytest.mark.asyncio
async def test_update_missing_404(svc):
    """更新不存在的科室 → 404。"""
    with pytest.raises(HTTPException) as exc:
        await svc.update("no-such-id", DepartmentUpdate(name="x"))
    assert exc.value.status_code == 404


# ── deactivate / activate ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deactivate_then_activate_roundtrip(svc):
    """停用是软删除（记录保留 is_active=False）；启用后恢复 True。"""
    dept = await svc.create(DepartmentCreate(name="康复科", code="rehab"))
    await svc.deactivate(dept.id)
    assert (await svc.get_by_id(dept.id)).is_active is False
    await svc.activate(dept.id)
    assert (await svc.get_by_id(dept.id)).is_active is True


@pytest.mark.asyncio
async def test_deactivate_missing_404(svc):
    """停用不存在的科室 → 404。"""
    with pytest.raises(HTTPException) as exc:
        await svc.deactivate("no-such-id")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_missing_404(svc):
    """启用不存在的科室 → 404。"""
    with pytest.raises(HTTPException) as exc:
        await svc.activate("no-such-id")
    assert exc.value.status_code == 404
