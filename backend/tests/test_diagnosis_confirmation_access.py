"""独立安全回归：诊断预览按接诊授权，确认内容不能脱离本次签发/修订正文。"""
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services.ai.record_renderer import render_record

TEXT = render_record("outpatient", {"western_diagnosis": "合成诊断甲；合成诊断乙"})
CONFIRMED = [
    {"name": "合成诊断甲", "category": "western", "is_primary": True},
    {"name": "合成诊断乙", "category": "western", "is_primary": False},
]


@pytest_asyncio.fixture
async def confirmation_client(async_db):
    """同患者他人接诊与另一患者接诊均造在本机临时库，不访问业务数据。"""
    async_db.add_all([Patient(id="confirm-p", name="合成患者甲"), Patient(id="other-p", name="合成患者乙")])
    for eid, pid, uid in (("own", "confirm-p", "doc-me"), ("same-patient", "confirm-p", "doc-other"), ("other-patient", "other-p", "doc-other")):
        async_db.add(Encounter(id=eid, patient_id=pid, doctor_id=uid,
            visit_type="outpatient", status="in_progress", visited_at=datetime(2026, 10, 12)))
        async_db.add(MedicalRecord(id=f"record-{eid}", encounter_id=eid, record_type="outpatient",
            status="editing" if eid == "own" else "submitted", current_version=1,
            submitted_at=None if eid == "own" else datetime(2026, 10, 12)))
        async_db.add(RecordVersion(medical_record_id=f"record-{eid}", version_no=1,
            content={"text": TEXT}, source="doctor_edited" if eid == "own" else "doctor_signed", triggered_by=uid))
    await async_db.commit()
    user = User(id="doc-me", username="synthetic", password_hash="unused", role="doctor", is_active=True)
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, user
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("eid", ["same-patient", "other-patient"])
@pytest.mark.parametrize("include_encounter", [True, False])
async def test_preview_does_not_accept_patient_level_or_id_only_access(confirmation_client, eid, include_encounter):
    """同患者有自己的接诊不代表可以读别人的接诊；省略接诊ID也不能绕过。"""
    client, _ = confirmation_client
    body = {"record_id": f"record-{eid}", "record_type": "outpatient", "content": TEXT}
    if include_encounter:
        body["encounter_id"] = eid
    response = await client.post("/api/v1/medical-records/diagnosis-preview", json=body)
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["nurse", "qc_officer", "radiologist"])
async def test_preview_requires_record_writing_role(confirmation_client, role):
    """即使账号恰是接诊owner，只读角色也不能使用签发确认入口。"""
    client, user = confirmation_client
    user.role = role
    response = await client.post("/api/v1/medical-records/diagnosis-preview", json={
        "encounter_id": "own", "record_id": "record-own", "record_type": "outpatient", "content": TEXT})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_preview_id_must_match_encounter_and_type(confirmation_client):
    """管理员跨接诊权限也不能掩盖客户端身份三元组不一致。"""
    client, user = confirmation_client
    user.role = "hospital_admin"
    for mismatch in ({"record_id": "record-same-patient"}, {"record_type": "emergency"}):
        body = {"encounter_id": "own", "record_id": "record-own", "record_type": "outpatient", "content": TEXT, **mismatch}
        assert (await client.post("/api/v1/medical-records/diagnosis-preview", json=body)).status_code in {400, 404, 422}


@pytest.mark.asyncio
async def test_admin_can_preview_foreign_signed_record_for_revision(confirmation_client):
    """合法管理员修订预览可仅提供文书ID，不能误套本人接诊限定。"""
    client, user = confirmation_client
    user.role = "hospital_admin"
    response = await client.post("/api/v1/medical-records/diagnosis-preview", json={
        "record_id": "record-same-patient", "record_type": "outpatient", "content": TEXT})
    assert response.status_code == 200
    assert {item["name"] for item in response.json()["diagnoses"]} == {"合成诊断甲", "合成诊断乙"}


INVALID_CONFIRMATIONS = [
    [],  # 显式空数组不能当作省略而回落到旧诊断。
    CONFIRMED[:1],
    [*CONFIRMED, {"name": "正文没有的诊断", "category": "western", "is_primary": False}],
    [CONFIRMED[0], CONFIRMED[0]],
    [{**row, "is_primary": True} for row in CONFIRMED],
    [{**row, "is_primary": False} for row in CONFIRMED],
    [{**CONFIRMED[0], "category": "tcm_disease"}, CONFIRMED[1]],
    [{**CONFIRMED[0], "is_primary": "yes"}, CONFIRMED[1]],
    [{**CONFIRMED[0], "code": "FORGED", "code_type": "ICD10"}, CONFIRMED[1]],
]


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", INVALID_CONFIRMATIONS)
@pytest.mark.parametrize("revise", [False, True])
async def test_invalid_confirmations_cannot_create_signed_versions(confirmation_client, async_db, confirmed, revise):
    """跳过预览直接提交也必须校验集合及唯一主诊断，拒绝后版本数不变。"""
    client, user = confirmation_client
    before = (await async_db.execute(select(func.count(RecordVersion.id)))).scalar_one()
    body = {"content": TEXT, "confirmed_diagnoses": confirmed}
    if revise:
        user.role = "hospital_admin"
        url = "/api/v1/admin/records/record-same-patient/revise"
        body["revise_reason"] = "合成安全回归"
    else:
        url = "/api/v1/medical-records/quick-save"
        body.update({"encounter_id": "own", "record_id": "record-own", "record_type": "outpatient"})
    response = await client.post(url, json=body)
    assert response.status_code in {400, 409, 422}, response.text
    assert (await async_db.execute(select(func.count(RecordVersion.id)))).scalar_one() == before


@pytest.mark.asyncio
async def test_confirmation_of_old_names_cannot_sign_changed_text(confirmation_client, async_db):
    """旧正文核对结果不能签发新诊断正文；预览不是授权凭证。"""
    client, _ = confirmation_client
    changed = render_record("outpatient", {"western_diagnosis": "合成诊断丙；合成诊断乙"})
    response = await client.post("/api/v1/medical-records/quick-save", json={
        "encounter_id": "own", "record_id": "record-own", "record_type": "outpatient",
        "content": changed, "confirmed_diagnoses": CONFIRMED})
    assert response.status_code in {400, 409, 422}
    record = await async_db.get(MedicalRecord, "record-own")
    assert record.status == "editing" and record.current_version == 1
