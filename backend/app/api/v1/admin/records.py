"""
管理后台病历管理接口（/api/v1/admin/records/*）

端点列表：
  GET /  分页查询所有已签发病历（可按医生 ID 筛选），含患者和医生信息

仅管理员可访问（require_admin）。
只返回 status='submitted' 的病历（已签发），草稿/生成中的病历不在此展示。
每条病历附带：患者姓名/性别、接诊医生姓名、病历内容预览（前 100 字）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User

router = APIRouter()


@router.get("")
async def list_all_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=50),
    doctor_id: str = Query(None, description="按医生 UUID 筛选，不传则返回所有医生的病历"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员查看所有已签发病历，可按医生筛选。

    联表查询：MedicalRecord → Encounter → Patient / User，一次获取完整信息。
    """
    offset = (page - 1) * page_size

    # 构建基础查询（联表获取接诊医生和患者信息）
    base = (
        select(MedicalRecord, Encounter, Patient, User)
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .join(User, Encounter.doctor_id == User.id)
        .where(MedicalRecord.status == "submitted")
    )
    if doctor_id:
        base = base.where(Encounter.doctor_id == doctor_id)

    # 先统计总数（用于分页）
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页查询，按签发时间倒序
    q = base.order_by(desc(MedicalRecord.submitted_at)).offset(offset).limit(page_size)
    rows = (await db.execute(q)).all()

    items = []
    for record, encounter, patient, doctor in rows:
        # 查询最新版本内容（取预览摘要）
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
