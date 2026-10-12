"""真实 PostgreSQL JSONB 往返后，签名及修订投影仍保持版本隔离。"""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.his_adapter.record_projection import freeze_record_projection
from app.his_adapter.writeback_builder import build_writeback_payload
from app.models.encounter import Diagnosis, Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services._record_signature import GENESIS_HASH, compute_sign_hash, verify_version_against
from app.services.admin_record_service import AdminRecordService
from app.services.ai.record_renderer import render_record


async def test_projection_jsonb_signature_and_revision_isolation(pg_with_tables, monkeypatch):
    """关闭会话后重读真实 JSONB，避免 SQLite 和 ORM 身份缓存掩盖版本串写。"""
    async def noop(*args, **kwargs):
        """只隔离缓存、审计外部副作用，投影、修订与回写构建使用真实业务代码。"""
    monkeypatch.setattr("app.services.admin_record_service.log_action", noop)
    monkeypatch.setattr("app.services.admin_record_service.invalidate_encounter_snapshot", noop)
    monkeypatch.setattr("app.config.settings.his_adapter_enabled", False)
    sessions = async_sessionmaker(pg_with_tables, expire_on_commit=False)
    text = render_record("outpatient", {
        "chief_complaint": "签发主诉", "western_diagnosis": "高血压病",
        "physical_exam_vitals": "T:36.5℃",
    })
    async with sessions() as db:
        # 真实 PG 校验外键，按依赖顺序创建合成医生、患者与接诊。
        db.add(User(id="projection-doc", username="projection-doc", password_hash="test-only",
                    real_name="测试医生", role="hospital_admin"))
        db.add(Patient(id="projection-p", name="合成测试患者"))
        await db.flush()
        db.add(Encounter(id="projection-e", patient_id="projection-p", doctor_id="projection-doc",
                         visit_type="outpatient", status="completed"))
        await db.flush()
        db.add(Diagnosis(id="projection-d", encounter_id="projection-e", name="高血压病",
                         category="western", code="I10", code_type="ICD10", is_primary=True))
        db.add(InquiryInput(id="projection-i", encounter_id="projection-e", chief_complaint="原问诊",
                            temperature="39"))
        await db.flush()
        projection = await freeze_record_projection(db, "projection-e", "outpatient", text)
        record = MedicalRecord(id="projection-r", encounter_id="projection-e", record_type="outpatient",
                               status="submitted", current_version=1, submitted_at=datetime(2026, 10, 12))
        db.add(record)
        await db.flush()
        version = RecordVersion(medical_record_id=record.id, version_no=1, triggered_by="projection-doc",
                                source="doctor_signed", content={"text": text, "his_projection": projection},
                                prev_hash=GENESIS_HASH)
        version.sign_hash = compute_sign_hash(
            content_text=text, patient_snapshot=None, doctor_id="projection-doc",
            submitted_at_iso=record.submitted_at.isoformat(), prev_hash=GENESIS_HASH, his_projection=projection,
        )
        db.add(version)
        await db.commit()
        original_content, original_hash = deepcopy(version.content), version.sign_hash

    async with sessions() as db:
        # 后续问诊变更已提交，也不能改变已签发版本的正文、测量值和诊断编码。
        inquiry = await db.get(InquiryInput, "projection-i")
        inquiry.chief_complaint, inquiry.temperature = "后改问诊", "40"
        diagnosis = await db.get(Diagnosis, "projection-d")
        diagnosis.code = "CHANGED"
        await db.commit()

    async with sessions() as db:
        record = await db.get(MedicalRecord, "projection-r")
        old = (await db.execute(select(RecordVersion))).scalar_one()
        assert old.content == original_content and verify_version_against(old, record)
        payload = await build_writeback_payload(db, "projection-e", record_id=record.id)
        assert payload["record"]["chief_complaint"] == "签发主诉"
        assert payload["vitals"] == {"temperature": "36.5"}
        assert payload["diagnoses"][0]["code"] == "I10"
        revised = render_record("outpatient", {
            "chief_complaint": "修订主诉", "western_diagnosis": "修订诊断", "physical_exam_vitals": "T:37℃",
        })
        await AdminRecordService(db).revise_record(
            record.id, revised, "核对最终诊断", SimpleNamespace(id="projection-doc"),
            confirmed_diagnoses=[{"name": "修订诊断", "category": "western", "is_primary": True}],
        )

    async with sessions() as db:
        # 再次跨会话读取：修订确认只改变新版本依据，旧 JSONB 和哈希保持原样。
        record = await db.get(MedicalRecord, "projection-r")
        old, new = (await db.execute(select(RecordVersion).order_by(RecordVersion.version_no))).scalars().all()
        assert old.content == original_content and old.sign_hash == original_hash
        assert new.prev_hash == original_hash
        assert all(verify_version_against(version, record) for version in (old, new))
        expected = [{"name": "修订诊断", "category": "western", "is_primary": True}]
        assert new.content["his_projection"]["diagnosis_basis"] == expected
        payload = await build_writeback_payload(db, "projection-e", record_id=record.id)
        assert payload["diagnoses"] == expected
        assert payload["record"]["chief_complaint"] == "修订主诉"
        assert payload["vitals"] == {"temperature": "37"}
