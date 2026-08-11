"""叫号队列端点 + 签发自动回写钩子测试。"""
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User


async def _mk_doctor(db, username="qdoc") -> User:
    doctor = User(username=username, password_hash="x", real_name="队列医生",
                  role="doctor", is_active=True)
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


async def _mk_encounter(db, doctor: User, *, his: bool, visit_no="V-q1") -> Encounter:
    patient = Patient(name="队列患者")
    db.add(patient)
    await db.flush()
    enc = Encounter(
        patient_id=patient.id, doctor_id=doctor.id, visit_type="outpatient",
        visit_no=visit_no, status="in_progress", visited_at=datetime.now(),
        his_external_ref={"source": "admit_push", "dept_name": "全科"} if his else None,
    )
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    return enc


@pytest_asyncio.fixture
async def client_ctx(async_db, monkeypatch):
    """开保险丝 + 依赖覆盖（DB / 登录医生），yield (client, doctor)。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    doctor = await _mk_doctor(async_db)
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doctor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, doctor
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_today_queue_returns_his_encounters_only(client_ctx, async_db):
    """今日队列只含 HIS 推送来源接诊，医生手动新建的不混入。"""
    client, doctor = client_ctx
    await _mk_encounter(async_db, doctor, his=True, visit_no="V-his")
    await _mk_encounter(async_db, doctor, his=False, visit_no="V-manual")

    res = await client.get("/api/v1/his/queue/today")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["visit_no"] == "V-his"
    assert items[0]["patient_name"] == "队列患者"
    assert items[0]["dept_name"] == "全科"
    assert items[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_today_queue_excludes_other_doctor(client_ctx, async_db):
    """别的医生的 HIS 接诊不出现在本医生队列。"""
    client, _doctor = client_ctx
    other = await _mk_doctor(async_db, username="other-doc")
    await _mk_encounter(async_db, other, his=True, visit_no="V-other")

    res = await client.get("/api/v1/his/queue/today")
    assert res.json()["items"] == []


@pytest.mark.asyncio
async def test_quick_save_dispatches_his_writeback(client_ctx, async_db, monkeypatch):
    """签发 HIS 来源接诊 → 派发回写；响应带 his_writeback=dispatched。"""
    client, doctor = client_ctx
    enc = await _mk_encounter(async_db, doctor, his=True, visit_no="V-sign")

    dispatched: list = []

    async def fake_dispatch(encounter_id, doctor_id, visit_no):
        dispatched.append((encounter_id, doctor_id, visit_no))

    from app.his_adapter import writeback_dispatch
    monkeypatch.setattr(writeback_dispatch, "dispatch_writeback", fake_dispatch)

    res = await client.post("/api/v1/medical-records/quick-save", json={
        "encounter_id": enc.id, "record_type": "outpatient", "content": "主诉：测试。",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["his_writeback"] == "dispatched"
    # create_task 派发的协程让出一拍后应已执行（fake 立即返回）
    import asyncio
    await asyncio.sleep(0)
    assert dispatched == [(enc.id, doctor.id, "V-sign")]


@pytest.mark.asyncio
async def test_quick_save_normal_encounter_no_writeback(client_ctx, async_db, monkeypatch):
    """普通 SaaS 接诊签发 → 不派发回写，his_writeback 为 null。"""
    client, doctor = client_ctx
    enc = await _mk_encounter(async_db, doctor, his=False, visit_no=None)

    called: list = []

    async def fake_dispatch(*args):
        called.append(args)

    from app.his_adapter import writeback_dispatch
    monkeypatch.setattr(writeback_dispatch, "dispatch_writeback", fake_dispatch)

    res = await client.post("/api/v1/medical-records/quick-save", json={
        "encounter_id": enc.id, "record_type": "outpatient", "content": "主诉：测试。",
    })
    assert res.status_code == 200
    assert res.json()["his_writeback"] is None
    assert called == []
