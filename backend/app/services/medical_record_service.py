"""
病历服务（app/services/medical_record_service.py）

职责：
  封装病历记录的完整生命周期管理：
  - create          : 为接诊创建新病历条目（空内容，等待 AI 生成或医生编辑）
  - get_by_id       : 按 ID 查询病历，可附加归属权校验（防止越权访问）
  - save_content    : 医生编辑病历内容，自动递增版本号（只读行锁防并发冲突）
  - quick_save      : 医生确认签发——保存最终内容 + 标记接诊为已完成
  - list_by_doctor  : 查询医生的历史签发病历（用于管理/归档）
  - get_versions    : 查询病历的所有版本列表（用于版本回溯）

版本控制设计：
  每次保存内容都会创建一条新 RecordVersion 记录，并递增 MedicalRecord.current_version。
  版本号单调递增，不可逆——即使回滚到旧内容，也会生成新版本号，确保完整审计链。

签发（quick_save）设计：
  签发 = 医生确认本次接诊处理完毕。签发后：
    1. MedicalRecord.status 设为 'submitted'，防止继续编辑
    2. Encounter.status 设为 'completed'，从进行中列表移除
  内容以 {"text": "..."} 格式存储（quick_save 模式），与结构化格式（各字段分开）并存，
  读取时由 encounter_service 统一做格式兼容处理。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.schemas.medical_record import MedicalRecordCreate, RecordContentUpdate


class MedicalRecordService:
    """病历数据访问服务，封装病历 CRUD 及版本控制逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: MedicalRecordCreate) -> MedicalRecord:
        """为接诊新建一条病历记录（初始状态 draft，内容为空）。

        每次 AI 生成病历时都会调用此方法先创建记录占位，
        之后由 AI 服务保存内容版本（source='ai_generated'）。
        """
        record = MedicalRecord(
            encounter_id=data.encounter_id,
            record_type=data.record_type,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_id(self, record_id: str, doctor_id: str | None = None) -> MedicalRecord:
        """按 ID 查询病历，可选附加归属权校验。

        Args:
            record_id: 病历 ID。
            doctor_id: 若传入，则同时校验该病历对应接诊的主治医生必须为此 ID，
                       防止医生 A 访问医生 B 的病历（越权访问）。

        Raises:
            HTTPException(403): 传入 doctor_id 但归属权不匹配（合并 "不存在" 和 "无权" 的响应，
                                 不暴露病历是否存在的信息）。
            HTTPException(404): 未传入 doctor_id 且病历不存在（管理员查询场景）。
        """
        if doctor_id:
            # 联表 Encounter 校验归属权，一次查询完成，避免二次 SELECT
            result = await self.db.execute(
                select(MedicalRecord)
                .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
                .where(MedicalRecord.id == record_id, Encounter.doctor_id == doctor_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=403, detail="病历不存在或无权访问")
            return record

        # 无归属权校验（管理员或内部调用场景）
        result = await self.db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id))
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="病历不存在")
        return record

    async def save_content(self, record_id: str, data: RecordContentUpdate, user_id: str):
        """医生编辑并保存病历内容，创建新版本。

        并发安全：使用 with_for_update() 行锁，防止两个请求同时写入时版本号冲突
        （例如两个标签页同时保存）。

        业务规则：
          - 已签发（status='submitted'）的病历不可再编辑，保障病历合法性。
          - 每次保存都追加一条 RecordVersion（source='doctor_edited'），不覆盖旧版本。

        Args:
            record_id: 病历 ID。
            data:      新内容（RecordContentUpdate 中的 content 字段，支持结构化 dict 或纯文本）。
            user_id:   操作医生 ID，写入版本的 triggered_by 字段，用于审计。

        Returns:
            {"ok": True, "version_no": 新版本号}
        """
        # 行锁查询：联表 Encounter 校验归属权 + 加锁防并发
        result = await self.db.execute(
            select(MedicalRecord)
            .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
            .where(MedicalRecord.id == record_id, Encounter.doctor_id == user_id)
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=403, detail="病历不存在或无权修改")
        if record.status == "submitted":
            raise HTTPException(status_code=403, detail="病历已签发，不可修改")

        # 版本号递增并创建新版本记录
        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record_id,
            version_no=new_version_no,
            content=data.content,
            source="doctor_edited",   # 标记来源：医生手动编辑
            triggered_by=user_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "editing"     # 重置为编辑中（如曾被 AI 标为其他状态）
        await self.db.commit()
        return {"ok": True, "version_no": new_version_no}

    async def quick_save(self, encounter_id: str, record_type: str, content: str, doctor_id: str) -> MedicalRecord:
        """签发病历：保存最终内容并将接诊状态标记为已完成。

        "签发"是医生确认本次接诊处理完毕的动作，触发后：
          1. 病历状态变为 submitted（不可继续编辑）
          2. 接诊状态变为 completed（从"进行中"列表消失）

        内容格式：以 {"text": content} 存储（quick_save 简化格式），
        读取时由 encounter_service.get_workspace_snapshot() 统一做格式兼容解包。

        并发安全：with_for_update() 防止同一接诊的两次并发签发请求产生重复病历。

        Args:
            encounter_id: 接诊 ID（不直接传入 record_id，由本方法查找或创建病历）。
            record_type:  病历类型（"outpatient" / "emergency" / "inpatient" 等）。
            content:      病历最终文本内容。
            doctor_id:    签发医生 ID，写入版本的 triggered_by 字段。

        Returns:
            签发后的 MedicalRecord ORM 对象（已 commit 并 refresh）。
        """
        # 加锁查找同接诊同类型的病历（防止并发重复签发）
        result = await self.db.execute(
            select(MedicalRecord).where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            ).with_for_update()
        )
        record = result.scalar_one_or_none()
        if not record:
            # 首次签发，病历记录尚未创建（极少数情况：直接签发跳过了 AI 生成步骤）
            record = MedicalRecord(encounter_id=encounter_id, record_type=record_type)
            self.db.add(record)
            await self.db.flush()  # 获取数据库生成的 id，后续 RecordVersion 需要引用

        # 创建签发版本（source='doctor_signed' 标记为医生签发，区别于 'doctor_edited'）
        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record.id,
            version_no=new_version_no,
            content={"text": content},    # quick_save 统一用 {"text": ...} 格式
            source="doctor_signed",
            triggered_by=doctor_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "submitted"
        record.submitted_at = datetime.now()

        # 同步完成接诊状态，使其从「进行中」列表消失
        enc_result = await self.db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = enc_result.scalar_one_or_none()
        if encounter:
            encounter.status = "completed"

        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def list_by_doctor(self, doctor_id: str, page: int = 1, page_size: int = 20) -> dict:
        """查询医生的历史签发病历列表（分页）。

        只返回 status='submitted' 的病历，按签发时间倒序排列。
        每条记录附带患者信息和病历内容预览（截取前 80 字）。

        Returns:
            {"total": 总条数, "items": [病历+患者信息列表]}
        """
        from app.models.patient import Patient
        from sqlalchemy import func

        offset = (page - 1) * page_size

        # 统计总数：联表 Encounter 过滤医生 + 只计签发病历
        count_q = (
            select(func.count())
            .select_from(MedicalRecord)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .where(Encounter.doctor_id == doctor_id, MedicalRecord.status == "submitted")
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        # 联表查询病历、接诊、患者，按签发时间倒序分页
        q = (
            select(MedicalRecord, Encounter, Patient)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .join(Patient, Encounter.patient_id == Patient.id)
            .where(Encounter.doctor_id == doctor_id, MedicalRecord.status == "submitted")
            .order_by(desc(MedicalRecord.submitted_at))
            .offset(offset)
            .limit(page_size)
        )
        rows = (await self.db.execute(q)).all()

        items = []
        for record, encounter, patient in rows:
            # 获取最新版本内容（用于生成预览摘要）
            ver_q = (
                select(RecordVersion)
                .where(RecordVersion.medical_record_id == record.id)
                .order_by(desc(RecordVersion.version_no))
                .limit(1)
            )
            ver = (await self.db.execute(ver_q)).scalar_one_or_none()
            # quick_save 格式 {"text": "..."} 取 text；其他格式作空串处理
            content_text = ver.content.get("text", "") if ver and isinstance(ver.content, dict) else ""
            items.append({
                "id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "submitted_at": record.submitted_at,
                "patient_name": patient.name,
                "patient_gender": patient.gender,
                "encounter_id": encounter.id,
                "content_preview": content_text[:80] + "..." if len(content_text) > 80 else content_text,
                "content": content_text,
            })
        return {"total": total, "items": items}

    async def get_versions(self, record_id: str):
        """获取病历的所有版本列表（按版本号倒序）。

        用于版本回溯面板，展示"谁在什么时候用什么方式修改了病历"。
        只返回元数据（版本号、来源、时间），不返回内容，减少传输量。

        source 字段含义：
          - 'ai_generated'  : AI 首次生成
          - 'ai_polished'   : AI 润色后的版本
          - 'doctor_edited' : 医生手动编辑
          - 'doctor_signed' : 医生签发时保存的最终版本
        """
        result = await self.db.execute(
            select(RecordVersion)
            .where(RecordVersion.medical_record_id == record_id)
            .order_by(RecordVersion.version_no.desc())
        )
        versions = result.scalars().all()
        return {
            "items": [
                {
                    "version_no": v.version_no,
                    "source": v.source,
                    "created_at": v.created_at,
                }
                for v in versions
            ]
        }
