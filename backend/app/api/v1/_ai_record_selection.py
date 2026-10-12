"""AI 改写前校验所选文书身份；生成结束后的保存仍需再次检查签发锁。"""
from fastapi import HTTPException
from sqlalchemy import select

from app.core.authz import assert_encounter_access
from app.core.request_context import bind_encounter_context
from app.models.medical_record import MedicalRecord


async def validate_ai_record_selection(db, req, current_user):
    """只允许在已授权接诊下改写匹配类型的未签发文书。"""
    encounter_id = getattr(req, "encounter_id", None)
    record_id = getattr(req, "medical_record_id", None)
    if record_id and not encounter_id:
        raise HTTPException(status_code=400, detail="选择病历必须提供接诊ID")
    if encounter_id:
        await assert_encounter_access(db, encounter_id, current_user)
    if record_id:
        record = (await db.execute(select(MedicalRecord).where(
            MedicalRecord.id == record_id,
            MedicalRecord.encounter_id == encounter_id,
            MedicalRecord.record_type == (req.record_type or "outpatient"),
        ))).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="所选病历不存在或不属于当前接诊及类型")
        if record.status == "submitted":
            raise HTTPException(status_code=403, detail="所选病历已签发，不可再编辑")
    bind_encounter_context(encounter_id=encounter_id, medical_record_id=record_id)
