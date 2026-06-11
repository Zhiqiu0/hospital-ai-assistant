"""
管理后台病历服务（app/services/admin_record_service.py）

2026-06-11 Round 5 迁移：业务逻辑从 app/api/v1/admin/records.py 下沉到 service 层，
路由层只保留请求解析 + 鉴权 + 调 service，行为零改变。

职责：
  - list_all_records : 分页查询所有已签发病历（4 表 JOIN：病历→接诊→患者/医生，
                       外联科室），附带病案首页快照与患者 fallback 字段
  - revise_record    : 管理员修订已签发病历——创建新 RecordVersion（旧版本永久保留）、
                       更新 current_version、写审计日志、失效接诊 snapshot 缓存

修订设计（合规要点）：
  已签发病历是法律文件，国家《病历书写基本规范》要求修正必须留痕。
  本系统的实现：
    - 不覆盖原版本，创建新 RecordVersion（version_no+1, source='admin_revise'）
    - 修订理由必填，写入 audit_logs.detail
    - record.current_version 指向新版本，但旧版本永久保留可查
    - 触发者（triggered_by）= 当前管理员账号
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services.audit_service import log_action
from app.services.encounter_service import invalidate_encounter_snapshot


class AdminRecordService:
    """管理后台病历数据访问服务，封装全院病历列表查询与管理员修订逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all_records(
        self,
        page: int,
        page_size: int,
        doctor_id: str | None = None,
    ) -> dict:
        """管理员分页查询所有已签发病历，可按医生筛选。

        联表查询：MedicalRecord → Encounter → Patient / User，一次获取完整信息。

        Args:
            page: 页码（从 1 开始）。
            page_size: 每页条数。
            doctor_id: 按医生 UUID 筛选，None 则返回所有医生的病历。

        Returns:
            {"total": 总数, "items": [病历摘要字典, ...]}，按签发时间倒序。
        """
        offset = (page - 1) * page_size

        # 构建基础查询（联表获取接诊医生 + 患者 + 科室信息）
        # outerjoin Department 是因为历史用户可能没填科室，避免漏数据
        # 注意：Department 模型在 app.models.user 里定义（项目早期约定）
        from app.models.user import Department

        base = (
            select(MedicalRecord, Encounter, Patient, User, Department)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .join(Patient, Encounter.patient_id == Patient.id)
            .join(User, Encounter.doctor_id == User.id)
            .outerjoin(Department, User.department_id == Department.id)
            .where(MedicalRecord.status == "submitted")
        )
        if doctor_id:
            base = base.where(Encounter.doctor_id == doctor_id)

        # 先统计总数（用于分页）
        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0

        # 分页查询，按签发时间倒序
        q = base.order_by(desc(MedicalRecord.submitted_at)).offset(offset).limit(page_size)
        rows = (await self.db.execute(q)).all()

        items = []
        for record, encounter, patient, doctor, dept in rows:
            # 查询最新版本内容（取预览摘要）
            ver_q = (
                select(RecordVersion)
                .where(RecordVersion.medical_record_id == record.id)
                .order_by(desc(RecordVersion.version_no))
                .limit(1)
            )
            ver = (await self.db.execute(ver_q)).scalar_one_or_none()
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
                # ── 病案首页快照（2026-05-16 加）─────────────────────────────
                # 优先用 patient_snapshot（签发那一刻冻结的身份信息）；为空（旧记录）
                # 才回落到当前 patient 实时字段。前端 RecordViewModal/导出/打印用它
                # 渲染顶部首页。
                "patient_snapshot": record.patient_snapshot,
                # 顺便补全当前 patient 字段做 fallback（前端 PatientSnapshot 字段为空时用）
                "patient_phone": patient.phone,
                "patient_id_card": patient.id_card,
                "patient_address": patient.address,
                "patient_ethnicity": patient.ethnicity,
                "patient_marital_status": patient.marital_status,
                "patient_occupation": patient.occupation,
                "patient_workplace": patient.workplace,
                "patient_contact_name": patient.contact_name,
                "patient_contact_phone": patient.contact_phone,
                "patient_contact_relation": patient.contact_relation,
                "patient_blood_type": patient.blood_type,
                "patient_birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
                "visit_type": encounter.visit_type,
                # Encounter.visited_at = 接诊开始时间（DateTime）；不是 InquiryInput.visit_time
                "visit_time": encounter.visited_at.isoformat() if encounter.visited_at else None,
                "bed_no": encounter.bed_no,
                "department_name": dept.name if dept else None,
            })

        return {"total": total, "items": items}

    async def revise_record(
        self,
        record_id: str,
        content: str,
        revise_reason: str,
        current_user,
    ) -> dict:
        """管理员修订已签发病历：创建新 RecordVersion，旧版本保留供审计。

        流程：
          1. 校验病历存在
          2. 创建新 RecordVersion（version_no = current_version + 1）
          3. 更新 record.current_version 指向新版本
          4. 写 audit_log（含修订理由）
          5. 失效 snapshot 缓存让医生工作台拉到最新版本

        Args:
            record_id: 病历 ID。
            content: 完整的新病历正文（前端提交修订后的全文，不是 diff）。
            revise_reason: 修订理由（必填，写入 audit_logs，永久留痕）。
            current_user: 当前管理员（用于 triggered_by 与审计日志署名）。

        Raises:
            HTTPException(404): 病历不存在。
        """
        record = (await self.db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id))).scalar_one_or_none()
        if record is None:
            raise HTTPException(status_code=404, detail="病历不存在")

        new_version_no = (record.current_version or 0) + 1
        new_version = RecordVersion(
            medical_record_id=record_id,
            version_no=new_version_no,
            # 保持 quick-save 的 {"text": ...} 结构，下游 _parse_record_content 已支持
            content={"text": content},
            source="admin_revise",
            triggered_by=current_user.id,
        )
        self.db.add(new_version)
        record.current_version = new_version_no
        await self.db.commit()
        await self.db.refresh(new_version)

        # 审计日志：理由写进 detail，永久留痕（patient/encounter id 也带上方便检索）
        await log_action(
            action="revise_record",
            user_id=current_user.id,
            user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
            user_role=getattr(current_user, "role", None),
            resource_type="medical_record",
            resource_id=record_id,
            detail=f"修订理由：{revise_reason}（新版本号：{new_version_no}）",
        )

        # 失效该接诊的 snapshot，让医生端工作台再打开能拿到最新内容
        await invalidate_encounter_snapshot(record.encounter_id)

        return {
            "ok": True,
            "record_id": record_id,
            "new_version_no": new_version_no,
            "revised_at": datetime.now().isoformat(),
        }
