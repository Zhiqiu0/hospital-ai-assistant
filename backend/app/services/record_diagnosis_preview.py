"""诊断核对预览：与签发/修订共用确定性正文投影及编码依据，仅查询不保存。"""
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.core.authz import assert_can_write_record, assert_encounter_access
from app.his_adapter._projection_diagnoses import enrich_diagnoses
from app.his_adapter._projection_parse import ProjectionError
from app.his_adapter.record_projection import load_diagnosis_basis, project_record
from app.models.medical_record import MedicalRecord, RecordVersion
from app.services._record_type_guard import assert_record_type_matches


async def preview_record_diagnoses(db, request, user) -> dict:
    """医生限本人接诊，管理员可修订跨医生文书；精确record_id还须匹配接诊与类型。"""
    assert_can_write_record(user)
    encounter = None
    previous = None
    if request.record_id:
        record = await db.get(MedicalRecord, request.record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="所选病历不存在")
        encounter = await assert_encounter_access(db, record.encounter_id, user)
        if request.encounter_id and request.encounter_id != record.encounter_id:
            raise HTTPException(status_code=404, detail="所选病历不属于当前接诊")
        if record.record_type != request.record_type:
            raise HTTPException(status_code=422, detail="所选病历类型与预览类型不一致")
        # 草稿精确选择仍属首签，使用当前已确认条目；已签发修订只允许历史快照富化。
        if record.status == "submitted":
            content = (await db.execute(select(RecordVersion.content).where(
                RecordVersion.medical_record_id == record.id,
                RecordVersion.version_no == record.current_version,
            ))).scalar_one_or_none()
            previous = content.get("his_projection", {}) if isinstance(content, dict) else {}
    elif request.encounter_id:
        encounter = await assert_encounter_access(db, request.encounter_id, user)
    if encounter is not None:
        assert_record_type_matches(encounter.visit_type, request.record_type)
    his_required = bool(settings.his_adapter_enabled and encounter is not None and encounter.his_external_ref)
    try:
        projection = project_record(request.record_type, request.content.replace("\x00", ""))
    except ProjectionError as exc:
        return {"diagnoses": [], "requires_confirmation": False, "projection_error": str(exc),
                "his_writeback_required": his_required}
    candidates = await load_diagnosis_basis(db, encounter.id if encounter else None, previous)
    diagnoses = enrich_diagnoses(projection["diagnoses"], candidates)
    return {
        "diagnoses": [{"name": item["name"], "category": item.get("category"),
                       "is_primary": item.get("is_primary", False), "code": item.get("code"),
                       "code_type": item.get("code_type")} for item in diagnoses],
        "requires_confirmation": bool(diagnoses), "projection_error": None,
        "his_writeback_required": his_required,
    }
