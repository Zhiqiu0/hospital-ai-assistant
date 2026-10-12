"""HIS回写测试的规范签发版本工厂，仅用于合成资料。"""
from datetime import datetime

from app.his_adapter.record_projection import freeze_record_projection
from app.models.medical_record import MedicalRecord, RecordVersion
from app.services.ai.record_renderer import render_record


async def seed_signed_projection(db, encounter_id, record_type="outpatient", data=None, text=None):
    """从模板正文冻结投影；诊断编码需由调用方事先添加显式诊断条目。"""
    text = text if text is not None else render_record(record_type, data or {})
    projection = await freeze_record_projection(db, encounter_id, record_type, text)
    record = MedicalRecord(encounter_id=encounter_id, record_type=record_type,
                           status="submitted", current_version=1, submitted_at=datetime(2026, 10, 12))
    db.add(record)
    await db.flush()
    version = RecordVersion(medical_record_id=record.id, version_no=1, source="doctor_signed",
                            content={"text": text, "his_projection": projection})
    db.add(version)
    await db.flush()
    return record, version
