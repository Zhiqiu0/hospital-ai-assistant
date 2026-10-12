"""最终正文诊断预览、显式主诊断确认及历史修订闭环的接口合同测试。"""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.medical_record import RecordVersion
from app.models.patient import Patient
from app.services.ai.record_renderer import render_record
from app.his_adapter.writeback_builder import build_writeback_payload
from his_projection_support import seed_signed_projection


@pytest_asyncio.fixture
async def confirmation_client(async_db, monkeypatch):
    """真实路由与数据库，隔离审计/缓存和HIS发送，不访问任何外部服务。"""
    async def noop(*args, **kwargs):
        pass
    monkeypatch.setattr("app.api.v1.medical_records_write.log_action", noop)
    monkeypatch.setattr("app.services.admin_record_service.log_action", noop)
    monkeypatch.setattr("app.services.admin_record_service.invalidate_encounter_snapshot", noop)
    monkeypatch.setattr("app.config.settings.his_adapter_enabled", False)
    async_db.add(Patient(id="confirm-p", name="测试患者"))
    async_db.add(Encounter(id="confirm-e", patient_id="confirm-p", doctor_id="doctor", visit_type="outpatient", status="in_progress"))
    await async_db.flush()
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="doctor", role="doctor", username="doctor")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_preview_then_confirm_new_primary_and_freeze(confirmation_client, async_db):
    """新名称无编码仍可明确选主诊断；后端不凭顺序猜，确认后可正常回写。"""
    text = render_record("outpatient", {"western_diagnosis": "诊断甲；诊断乙"})
    response = await confirmation_client.post("/api/v1/medical-records/diagnosis-preview", json={
        "encounter_id": "confirm-e", "record_type": "outpatient", "content": text,
    })
    assert response.status_code == 200
    preview = response.json()
    assert preview["requires_confirmation"] is True and preview["projection_error"] is None
    assert preview["his_writeback_required"] is False
    assert [item["name"] for item in preview["diagnoses"]] == ["诊断甲", "诊断乙"]
    assert all(item["code"] is None and item["is_primary"] is False for item in preview["diagnoses"])
    confirmed = [{"name": "诊断甲", "category": "western", "is_primary": False},
                 {"name": "诊断乙", "category": "western", "is_primary": True}]
    response = await confirmation_client.post("/api/v1/medical-records/quick-save", json={
        "encounter_id": "confirm-e", "record_type": "outpatient", "content": text,
        "confirmed_diagnoses": confirmed,
    })
    assert response.status_code == 200, response.text
    payload = await build_writeback_payload(async_db, "confirm-e")
    assert payload["diagnoses"][0] == {"name": "诊断乙", "category": "western", "is_primary": True}
    version = (await async_db.execute(select(RecordVersion))).scalar_one()
    assert version.content["his_projection"]["diagnosis_basis"] == payload["diagnoses"]
    # 网络重试同样确认保持幂等；同正文换主诊断必须走修订，不能200假装已经改好。
    same = await confirmation_client.post("/api/v1/medical-records/quick-save", json={
        "encounter_id": "confirm-e", "record_type": "outpatient", "content": text,
        "confirmed_diagnoses": confirmed,
    })
    assert same.status_code == 200
    changed = [{**item, "is_primary": not item["is_primary"]} for item in confirmed]
    rejected = await confirmation_client.post("/api/v1/medical-records/quick-save", json={
        "encounter_id": "confirm-e", "record_type": "outpatient", "content": text,
        "confirmed_diagnoses": changed,
    })
    assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_admin_confirms_new_name_on_legacy_record_without_basis(confirmation_client, async_db):
    """历史无快照及主诊断改名不再永久失败，管理员明确确认后只新建版本。"""
    record, old = await seed_signed_projection(async_db, "confirm-e", text="旧自由正文")
    # 模拟上线前没有投影依据的历史版本。
    old.content = {"text": "旧自由正文"}
    await async_db.flush()
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="admin", role="hospital_admin", username="admin")
    text = render_record("outpatient", {"western_diagnosis": "新主诊断"})
    preview = await confirmation_client.post("/api/v1/medical-records/diagnosis-preview", json={
        "record_id": record.id, "record_type": "outpatient", "content": text,
    })
    assert preview.status_code == 200
    assert preview.json()["diagnoses"][0]["code"] is None
    response = await confirmation_client.post(f"/api/v1/admin/records/{record.id}/revise", json={
        "content": text, "revise_reason": "核对最终诊断", "confirmed_diagnoses": [
            {"name": "新主诊断", "category": "western", "is_primary": True}],
    })
    assert response.status_code == 200, response.text
    payload = await build_writeback_payload(async_db, "confirm-e", record_id=record.id)
    assert payload["diagnoses"] == [{"name": "新主诊断", "category": "western", "is_primary": True}]
    assert old.content == {"text": "旧自由正文"}
    # 再次只改主诉时，无须重新发明主诊断依据，上一确认版本已冻结新选择。
    second_text = render_record("outpatient", {"chief_complaint": "补充主诉", "western_diagnosis": "新主诊断"})
    response = await confirmation_client.post(f"/api/v1/admin/records/{record.id}/revise", json={
        "content": second_text, "revise_reason": "核对主诉",
    })
    assert response.status_code == 200
    second = await build_writeback_payload(async_db, "confirm-e", record_id=record.id)
    assert second["diagnoses"] == payload["diagnoses"]


@pytest.mark.asyncio
async def test_quickstart_and_bad_format_preview_are_read_only(confirmation_client):
    """无接诊quickstart可预览，格式错误单独返回而不假造诊断或要求无意义确认。"""
    response = await confirmation_client.post("/api/v1/medical-records/diagnosis-preview", json={
        "record_type": "outpatient", "content": "自由正文",
    })
    assert response.status_code == 200
    assert response.json()["projection_error"]
    assert response.json()["requires_confirmation"] is False
    assert response.json()["diagnoses"] == []


def test_confirmation_is_in_openapi_contract():
    """CI合同：前端依赖的预览路径和两个提交字段必须进入OpenAPI schema。"""
    schema = app.openapi()
    assert "/api/v1/medical-records/diagnosis-preview" in schema["paths"]
    for name in ("QuickSaveRequest", "ReviseRecordRequest"):
        assert "confirmed_diagnoses" in schema["components"]["schemas"][name]["properties"]
