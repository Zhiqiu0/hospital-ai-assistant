"""角色守卫回归测试（2026-08-14 第八轮审计）。

本项目反复出问题的形态是**同类端点守卫清单不一致**：同一种操作，A 端点挂了
守卫、B 端点没挂。第六轮给 quick-start 补 assert_can_write_record 时写下的理由
（"护士自建接诊后就成了接诊医生，病历署名落到护士头上"）逐字适用于
POST /encounters，却没跟着补，于是形成一条完整越权链：

    护士 POST /encounters 自建接诊（实测 201）
      → 成为该接诊的 doctor_id
      → assert_encounter_access 从此对她全部放行
      → POST progress-notes 写出署自己名的病程记录（实测 201）
      → PATCH status=submitted 签发（实测 200）

医院的硬要求是「病历上写的名字必须是接诊医生本人」。本文件把每个环节
从"实测能过"锁成"必须 403"。
"""

from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User


def _user(uid: str, role: str):
    return User(
        id=uid, username=f"u_{uid}", password_hash="x",
        real_name=f"测试{role}", role=role, is_active=True,
    )


@pytest_asyncio.fixture
async def seeded(async_db):
    """一个患者 + 一条挂在护士名下的接诊（模拟调岗/历史遗留场景）。"""
    patient = Patient(id="pat-1", name="张三", birth_date=date(1970, 1, 1))
    enc_nurse = Encounter(
        id="enc-nurse", patient_id="pat-1", doctor_id="u-nurse",
        visit_type="inpatient", status="in_progress", visited_at=datetime(2026, 8, 1),
    )
    async_db.add_all([patient, enc_nurse])
    await async_db.commit()
    return {"patient": patient, "enc_nurse": enc_nurse}


def _client_as(async_db, uid: str, role: str):
    async def _make() -> AsyncGenerator[AsyncClient, None]:
        app.dependency_overrides[get_db] = lambda: async_db
        app.dependency_overrides[get_current_user] = lambda: _user(uid, role)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()
    return _make()


NON_CLINICAL = ["nurse", "radiologist"]


# ── ① 越权链的入口：自建接诊 ────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("role", NON_CLINICAL)
async def test_非临床角色不能自建接诊(async_db, seeded, role):
    """修复前实测 201（doctor_id = 自己），与 quick-start 的 403 自相矛盾。"""
    async for ac in _client_as(async_db, f"u-{role}", role):
        r = await ac.post(
            "/api/v1/encounters",
            json={"patient_id": "pat-1", "visit_type": "outpatient"},
        )
        assert r.status_code == 403, f"{role} 仍能自建接诊并把自己设成接诊医生"


@pytest.mark.asyncio
async def test_医生仍然可以自建接诊(async_db, seeded):
    """防过度收紧——这是医生的正常操作。"""
    async for ac in _client_as(async_db, "u-doc", "doctor"):
        r = await ac.post(
            "/api/v1/encounters",
            json={"patient_id": "pat-1", "visit_type": "outpatient"},
        )
        assert r.status_code == 201


# ── ② 病历正文写入（本文件四个写端点里唯一漏挂的那个）────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("role", NON_CLINICAL)
async def test_非临床角色不能写病历正文(async_db, seeded, role):
    async for ac in _client_as(async_db, "u-nurse", role):
        r = await ac.put(
            "/api/v1/medical-records/rec-any/content",
            json={"content": {"text": "越权写入的病历正文"}},
        )
        # 403=角色被挡住（期望）；404 说明先撞了归属/存在性检查也算没写成，
        # 但这里断言必须是 403——角色守卫应当先于资源查找生效。
        assert r.status_code == 403, f"{role} 未被角色守卫拦下（得到 {r.status_code}）"


# ── ③ 病程记录：写 + 签发 ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("role", NON_CLINICAL)
async def test_非临床角色不能写病程记录(async_db, seeded, role):
    """接诊挂在其名下（调岗场景），归属校验会放行，必须靠角色守卫挡住。"""
    async for ac in _client_as(async_db, "u-nurse", role):
        r = await ac.post(
            "/api/v1/encounters/enc-nurse/progress-notes",
            json={"note_type": "course_record", "content": "越权写的病程"},
        )
        assert r.status_code == 403, f"{role} 写出了署自己名的病程记录"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", NON_CLINICAL)
async def test_非临床角色不能签发病程记录(async_db, seeded, role):
    async for ac in _client_as(async_db, "u-nurse", role):
        r = await ac.patch(
            "/api/v1/encounters/enc-nurse/progress-notes/note-any",
            json={"status": "submitted"},
        )
        assert r.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", NON_CLINICAL)
async def test_非临床角色不能删病程记录(async_db, seeded, role):
    async for ac in _client_as(async_db, "u-nurse", role):
        r = await ac.delete("/api/v1/encounters/enc-nurse/progress-notes/note-any")
        assert r.status_code == 403


# ── ④ HIS 工号映射的角色约束 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_his工号映射拒绝非临床角色(async_db):
    """医院给的是**全院名单**（含自助机/护工/财务），角色配错就会派错人。"""
    from app.his_adapter.admit_service import AdmitError, _map_doctor

    async_db.add(_user("u-nurse2", "nurse"))
    nurse = (await async_db.execute(
        __import__("sqlalchemy").select(User).where(User.id == "u-nurse2")
    )).scalar_one()
    nurse.employee_no = "N9001"
    await async_db.commit()

    with pytest.raises(AdmitError) as exc:
        await _map_doctor(async_db, "N9001")
    # 要能区分「查无此工号」与「角色不对」，否则联调现场排查成本很高
    assert "不是可书写病历的角色" in str(exc.value.message)


@pytest.mark.asyncio
async def test_his工号映射正常派给医生(async_db):
    from app.his_adapter.admit_service import _map_doctor

    async_db.add(_user("u-doc2", "doctor"))
    doc = (await async_db.execute(
        __import__("sqlalchemy").select(User).where(User.id == "u-doc2")
    )).scalar_one()
    doc.employee_no = "D1001"
    await async_db.commit()

    mapped = await _map_doctor(async_db, "D1001")
    assert mapped.id == "u-doc2"
