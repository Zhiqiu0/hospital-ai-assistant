"""
管理后台病历管理接口（/api/v1/admin/records/*）

端点列表：
  GET  /                 分页查询所有已签发病历（可按医生 ID 筛选），含患者和医生信息
  POST /{record_id}/revise  管理员修订已签发病历（创建新 RecordVersion，旧版本保留）

仅管理员可访问（require_admin）。
只返回 status='submitted' 的病历（已签发），草稿/生成中的病历不在此展示。
每条病历附带：患者姓名/性别、接诊医生姓名、病历内容预览（前 100 字）。

修订设计（合规要点）：
  已签发病历是法律文件，国家《病历书写基本规范》要求修正必须留痕。
  本系统的实现：
    - 不覆盖原版本，创建新 RecordVersion（version_no+1, source='admin_revise'）
    - 修订理由必填，写入 audit_logs.detail
    - record.current_version 指向新版本，但旧版本永久保留可查
    - 触发者（triggered_by）= 当前管理员账号
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services.audit_service import log_action
from app.services.encounter_service import invalidate_encounter_snapshot

router = APIRouter()


class ReviseRecordRequest(BaseModel):
    """管理员修订病历请求体。

    content: 完整的新病历正文（前端提交修订后的全文，不是 diff）
    revise_reason: 修订理由（必填，写入 audit_logs，永久留痕）
    """

    content: str = Field(min_length=1)
    revise_reason: str = Field(min_length=1, max_length=500)


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


@router.post("/{record_id}/revise")
async def revise_record(
    record_id: str,
    data: ReviseRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员修订已签发病历：创建新 RecordVersion，旧版本保留供审计。

    流程：
      1. 校验病历存在
      2. 创建新 RecordVersion（version_no = current_version + 1）
      3. 更新 record.current_version 指向新版本
      4. 写 audit_log（含修订理由）
      5. 失效 snapshot 缓存让医生工作台拉到最新版本
    """
    record = (await db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id))).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="病历不存在")

    new_version_no = (record.current_version or 0) + 1
    new_version = RecordVersion(
        medical_record_id=record_id,
        version_no=new_version_no,
        # 保持 quick-save 的 {"text": ...} 结构，下游 _parse_record_content 已支持
        content={"text": data.content},
        source="admin_revise",
        triggered_by=current_user.id,
    )
    db.add(new_version)
    record.current_version = new_version_no
    await db.commit()
    await db.refresh(new_version)

    # 审计日志：理由写进 detail，永久留痕（patient/encounter id 也带上方便检索）
    await log_action(
        action="revise_record",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="medical_record",
        resource_id=record_id,
        detail=f"修订理由：{data.revise_reason}（新版本号：{new_version_no}）",
    )

    # 失效该接诊的 snapshot，让医生端工作台再打开能拿到最新内容
    await invalidate_encounter_snapshot(record.encounter_id)

    return {
        "ok": True,
        "record_id": record_id,
        "new_version_no": new_version_no,
        "revised_at": datetime.now().isoformat(),
    }
