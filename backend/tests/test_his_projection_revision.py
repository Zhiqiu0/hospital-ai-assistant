"""管理员修订的HIS投影与版本签名回归：正文/编码必须属于同一个历史版本。"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.his_adapter.record_projection import freeze_record_projection
from app.his_adapter.writeback_builder import build_writeback_payload
from app.models.encounter import Diagnosis, Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services._record_signature import GENESIS_HASH, compute_sign_hash, verify_version_against
from app.services.admin_record_service import AdminRecordService
from app.services.ai.record_renderer import render_record


@pytest.mark.asyncio
async def test_revision_freezes_new_text_with_only_previous_version_codes(async_db, monkeypatch):
    """普通修订沿用同名历史代码，后来接诊修改不得污染；所有版本签名仍可验证。"""
    async def noop(*args, **kwargs):
        """隔离测试无关的缓存和审计外部副作用。"""
    monkeypatch.setattr("app.services.admin_record_service.log_action", noop)
    monkeypatch.setattr("app.services.admin_record_service.invalidate_encounter_snapshot", noop)
    async_db.add(Patient(id="revision-p", name="测试患者"))
    async_db.add(Encounter(id="revision-e", patient_id="revision-p", doctor_id="doc", visit_type="outpatient", status="completed"))
    diagnosis = Diagnosis(encounter_id="revision-e", name="高血压病", category="western", code="I10", code_type="ICD10", is_primary=True)
    async_db.add(diagnosis)
    text = render_record("outpatient", {"chief_complaint": "旧主诉", "western_diagnosis": "高血压病"})
    projection = await freeze_record_projection(async_db, "revision-e", "outpatient", text)
    record = MedicalRecord(id="revision-r", encounter_id="revision-e", record_type="outpatient",
                           status="submitted", current_version=1, submitted_at=datetime(2026, 10, 12))
    version = RecordVersion(medical_record_id=record.id, version_no=1, triggered_by="doc", source="doctor_signed",
        content={"text": text, "his_projection": projection}, prev_hash=GENESIS_HASH)
    version.sign_hash = compute_sign_hash(content_text=text, patient_snapshot=None, doctor_id="doc",
        submitted_at_iso=record.submitted_at.isoformat(), prev_hash=GENESIS_HASH, his_projection=projection)
    async_db.add_all([record, version])
    await async_db.commit()
    diagnosis.code = "NEW"
    await async_db.commit()
    revised = render_record("outpatient", {"chief_complaint": "新主诉", "western_diagnosis": "高血压病"})
    await AdminRecordService(async_db).revise_record(record.id, revised, "核对主诉", SimpleNamespace(id="admin"))
    payload = await build_writeback_payload(async_db, record.encounter_id, record_id=record.id)
    assert payload["record"]["chief_complaint"] == "新主诉"
    assert payload["diagnoses"][0]["code"] == "I10"
    versions = (await async_db.execute(select(RecordVersion).where(RecordVersion.medical_record_id == record.id))).scalars().all()
    assert len(versions) == 2
    assert all(verify_version_against(item, record) for item in versions)
    # 无明确主诊断确认时，改名修订可保存，但回写必须失败，不假装采用新名字的旧编码。
    renamed = render_record("outpatient", {"western_diagnosis": "新诊断名称"})
    await AdminRecordService(async_db).revise_record(record.id, renamed, "修改诊断", SimpleNamespace(id="admin"))
    with pytest.raises(ValueError, match="主诊断"):
        await build_writeback_payload(async_db, record.encounter_id, record_id=record.id)
