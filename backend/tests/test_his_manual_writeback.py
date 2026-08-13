"""手动回写端点单测（2026-08-13 复检修复：改走派发链路）。

修复前该端点就地调 send_writeback，只看本进程的 WS 连接——生产 2 worker 下
厂商长连接只挂在其中一个进程，请求落错 worker 就误判「WS 未连接」返回 skipped，
还会把队列上的回写状态覆写坏，医生反复点击结果随机。
改为与签发钩子相同的 dispatch_writeback：由持有连接的 worker 抢占执行。
"""
from datetime import date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.models.encounter import Encounter
from app.models.patient import Patient


@pytest_asyncio.fixture
async def wb_client(async_db, monkeypatch):
    """开保险丝 + 覆盖鉴权与 DB 依赖，返回 (client, encounter_id, 派发记录)。"""
    from app.core.security import get_current_user
    from app.database import get_db
    from app.main import app
    from app.models.user import User

    monkeypatch.setattr(settings, "his_adapter_enabled", True)

    doctor = User(username="wb-doc", password_hash="x", real_name="回写医生", role="doctor")
    async_db.add(doctor)
    patient = Patient(name="回写患者", birth_date=date(1990, 1, 1))
    async_db.add(patient)
    await async_db.flush()
    enc = Encounter(
        patient_id=patient.id, doctor_id=doctor.id, visit_type="outpatient",
        visit_no="V-WB-1", status="in_progress", visited_at=datetime.now(),
        his_external_ref={"source": "admit_push", "hospital_code": "H1"},
    )
    async_db.add(enc)
    await async_db.commit()

    # 记录派发调用，验证走的是派发而非就地执行
    dispatched: list[tuple] = []

    from app.his_adapter import writeback_dispatch

    async def fake_dispatch(encounter_id, doctor_id, visit_no):
        dispatched.append((encounter_id, doctor_id, visit_no))

    monkeypatch.setattr(writeback_dispatch, "dispatch_writeback", fake_dispatch)

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doctor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, enc.id, dispatched
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_manual_writeback_goes_through_dispatch(wb_client):
    """手动回写走派发：返回 dispatched，且派发函数被调用（带就诊号用于路由回来源诊室）。"""
    client, enc_id, dispatched = wb_client
    res = await client.post(f"/api/v1/his/encounter/{enc_id}/writeback")

    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "dispatched"

    # 关键：确实走了派发（而不是就地 send_writeback 误判 WS 离线）
    assert len(dispatched) == 1
    assert dispatched[0][0] == enc_id
    assert dispatched[0][2] == "V-WB-1"


@pytest.mark.asyncio
async def test_manual_writeback_rejects_non_his_encounter(async_db, monkeypatch):
    """非 HIS 来源的接诊不该发起回写（避免无意义派发与状态污染）。"""
    from app.core.security import get_current_user
    from app.database import get_db
    from app.main import app
    from app.models.user import User

    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    doctor = User(username="wb-doc2", password_hash="x", real_name="医生2", role="doctor")
    async_db.add(doctor)
    patient = Patient(name="普通患者", birth_date=date(1990, 1, 1))
    async_db.add(patient)
    await async_db.flush()
    enc = Encounter(patient_id=patient.id, doctor_id=doctor.id, visit_type="outpatient",
                    status="in_progress", visited_at=datetime.now())  # 无 his_external_ref
    async_db.add(enc)
    await async_db.commit()

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doctor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(f"/api/v1/his/encounter/{enc.id}/writeback")
    app.dependency_overrides.clear()

    assert res.json()["code"] == 40005
