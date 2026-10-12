"""按接诊、类型及可选主键锁定待写草稿；显式主键绝不回落或续建。"""
from fastapi import HTTPException
from sqlalchemy import select
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord


async def load_writable_draft(db, encounter_id, record_type, record_id=None):
    """保持 encounter→record 的统一锁顺序，防止首稿并发和签发竞争。"""
    await db.execute(select(Encounter.id).where(Encounter.id == encounter_id).with_for_update())
    record = (await db.execute(select(MedicalRecord).where(
        MedicalRecord.encounter_id == encounter_id,
        MedicalRecord.record_type == record_type,
        *([MedicalRecord.id == record_id] if record_id else []),
    ).order_by(MedicalRecord.updated_at.desc()).with_for_update())).scalars().first()
    if record_id and record is None:
        raise HTTPException(status_code=404, detail="所选病历不存在或不属于当前接诊及类型")
    if record_id and record.status == "submitted":
        raise HTTPException(status_code=403, detail="所选病历已签发，不可再编辑")
    return record
