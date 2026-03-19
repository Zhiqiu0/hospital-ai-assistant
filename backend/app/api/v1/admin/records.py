"""管理员查看所有病历"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.core.security import require_admin
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User

router = APIRouter()


@router.get("")
async def list_all_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=50),
    doctor_id: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员查看所有签发病历，可按医生筛选"""
    offset = (page - 1) * page_size

    base = (
        select(MedicalRecord, Encounter, Patient, User)
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .join(User, Encounter.doctor_id == User.id)
        .where(MedicalRecord.status == "submitted")
    )
    if doctor_id:
        base = base.where(Encounter.doctor_id == doctor_id)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    q = base.order_by(desc(MedicalRecord.submitted_at)).offset(offset).limit(page_size)
    rows = (await db.execute(q)).all()

    items = []
    for record, encounter, patient, doctor in rows:
        ver_q = (
            select(RecordVersion)
            .where(RecordVersion.medical_record_id == record.id)
            .order_by(desc(RecordVersion.version_no))
            .limit(1)
        )
        ver = (await db.execute(ver_q)).scalar_one_or_none()
        content_text = ver.content.get("text", "") if ver and isinstance(ver.content, dict) else ""
        items.append({
            "id": record.id,
            "record_type": record.record_type,
            "status": record.status,
            "submitted_at": record.submitted_at,
            "patient_name": patient.name,
            "patient_gender": patient.gender,
            "doctor_name": doctor.real_name,
            "doctor_id": doctor.id,
            "encounter_id": encounter.id,
            "content_preview": content_text[:100] + "..." if len(content_text) > 100 else content_text,
            "content": content_text,
        })

    return {"total": total, "items": items}
