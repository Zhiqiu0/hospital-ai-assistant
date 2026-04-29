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
import logging
from datetime import datetime
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.schemas.medical_record import MedicalRecordCreate, RecordContentUpdate
from app.utils.age import calc_age

# 模块级 logger：病历签发是核心业务里程碑，单独 INFO 级埋点便于运维复盘
logger = logging.getLogger(__name__)


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
        # 病历变更，工作台快照失效
        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(record.encounter_id)
        return {"ok": True, "version_no": new_version_no}

    async def auto_save_draft(
        self,
        encounter_id: str,
        record_type: str,
        content: str,
        user_id: str,
        expected_updated_at: Optional[datetime] = None,
    ) -> dict:
        """医生编辑器输入 / auto-save 防抖触发——把当前内容覆写到 draft 版本。

        与 save_ai_draft 区别：save_ai_draft 是 AI 生成完毕的"批次保存"，每次创建
        新 RecordVersion；本方法面向高频 5 秒一次的 auto-save，**不创建新版本**，
        只 UPDATE 当前 version 的 content——避免半小时几百个版本的爆炸式增长。

        乐观锁：调用方传入 expected_updated_at 时校验记录版本号；不匹配返 409。
        前端单设备场景一般不会触发；多设备并发编辑时这是唯一的冲突保护。

        Returns:
            {"record_id": ..., "version_no": ..., "updated_at": ISO 字符串}
            updated_at 给前端下次 auto-save 带回作为乐观锁凭证。
        Raises:
            HTTPException(409): 乐观锁冲突，调用方应提示"内容已被其他设备修改"
            HTTPException(403): 病历已签发，不可再编辑
        """
        result = await self.db.execute(
            select(MedicalRecord)
            .where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            )
            .order_by(MedicalRecord.updated_at.desc())
            .with_for_update()
        )
        record = result.scalars().first()

        if record is not None and record.status == "submitted":
            raise HTTPException(status_code=403, detail="病历已签发，不可再编辑")

        # 乐观锁校验（只在传入预期值时启用——AI 生成那次首发不需要）
        if expected_updated_at is not None and record is not None:
            # 数据库 updated_at 可能比预期值更新（其他设备已写过）→ 拒绝
            if record.updated_at and record.updated_at > expected_updated_at:
                raise HTTPException(
                    status_code=409,
                    detail="病历已被其他设备修改，请刷新后重试",
                )

        if record is None:
            # 首次 auto-save：建 record + 第一个 version
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=1,
            )
            self.db.add(record)
            await self.db.flush()
            version = RecordVersion(
                medical_record_id=record.id,
                version_no=1,
                content={"text": content},
                source="ai_generated",  # auto-save 起点常常是 AI 生成的，统一标这个
                triggered_by=user_id,
            )
            self.db.add(version)
        else:
            # 已有 record：UPDATE 当前 version 的 content（关键：不增加 version_no）
            ver_result = await self.db.execute(
                select(RecordVersion)
                .where(
                    RecordVersion.medical_record_id == record.id,
                    RecordVersion.version_no == record.current_version,
                )
                .with_for_update()
            )
            current_version = ver_result.scalar_one_or_none()
            if current_version is None:
                # 异常情况：record 存在但当前 version 不存在——创建一条
                current_version = RecordVersion(
                    medical_record_id=record.id,
                    version_no=record.current_version,
                    content={"text": content},
                    source="ai_generated",
                    triggered_by=user_id,
                )
                self.db.add(current_version)
            else:
                current_version.content = {"text": content}
            record.status = "editing"

        # 强制刷新 record.updated_at——SQLAlchemy onupdate 只在字段实际改变时触发，
        # 但 auto-save 经常 status 还是 "editing"，等于不更新 updated_at；
        # 这会让乐观锁失效（多设备冲突时两边的 expected_updated_at 都对得上）。
        # 显式 set 确保每次 auto-save 都推进 updated_at。
        record.updated_at = datetime.now()

        await self.db.commit()
        await self.db.refresh(record)

        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)

        return {
            "record_id": record.id,
            "version_no": record.current_version,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    async def save_ai_draft(
        self,
        encounter_id: str,
        record_type: str,
        content: str,
        user_id: str,
    ) -> dict:
        """AI 生成完毕保存草稿（不签发，不动接诊状态）。

        与 save_content 的差异：
          - save_content 要求 record_id 已知（医生编辑场景）
          - save_ai_draft 用 (encounter_id, record_type) upsert：
            * 该接诊该类型 record 不存在 → 创建一条 + 新版本
            * 已存在且非 submitted → 在原 record 上加新版本，状态保持 editing
            * 已签发（submitted）→ 跳过保存，返回原 record（不让 AI 覆盖签发病历）

        为什么必要：解决"AI 生成的病历只在前端 zustand store，logout 后清空 →
        DB 没数据可恢复 → 医生开心写一半的草稿全丢"的合规事故。

        Returns:
            {"record_id": ..., "version_no": ..., "saved": bool}
            saved=False 表示已签发跳过保存。
        """
        result = await self.db.execute(
            select(MedicalRecord)
            .where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            )
            .order_by(MedicalRecord.updated_at.desc())
            .with_for_update()
        )
        record = result.scalars().first()

        # 已签发病历不让 AI 覆盖（医生最终确认过的版本是法定证据）
        if record is not None and record.status == "submitted":
            return {"record_id": record.id, "version_no": record.current_version, "saved": False}

        if record is None:
            record = MedicalRecord(
                encounter_id=encounter_id,
                record_type=record_type,
                status="editing",
                current_version=0,
            )
            self.db.add(record)
            await self.db.flush()  # 拿到 record.id

        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record.id,
            version_no=new_version_no,
            content={"text": content},  # 与 quick_save 保持同一存储格式
            source="ai_generated",
            triggered_by=user_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "editing"
        await self.db.commit()

        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(encounter_id)
        return {"record_id": record.id, "version_no": new_version_no, "saved": True}

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

        # 接诊关闭策略：
        #   - 门诊/急诊：一次接诊 = 一份病历，签发即结束 → 关闭接诊
        #   - 住院：一次住院会有多份病历（入院记录/病程/查房/出院小结...），
        #     签发一份不代表出院，接诊状态保持 in_progress；将来由
        #     专门的"办理出院"动作关闭接诊。
        enc_result = await self.db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = enc_result.scalar_one_or_none()
        encounter_closed = False
        if encounter and encounter.visit_type != "inpatient":
            encounter.status = "completed"
            encounter_closed = True

        await self.db.commit()
        await self.db.refresh(record)
        # 失效缓存：snapshot 一定要失效（病历内容变了）；
        # my_encounters 列表缓存只在接诊真的关闭时才失效
        from app.services.encounter_service import (
            invalidate_encounter_snapshot,
            invalidate_my_encounters,
        )
        await invalidate_encounter_snapshot(encounter_id)
        if encounter_closed:
            await invalidate_my_encounters(encounter.doctor_id)
        # 业务里程碑：签发完成后埋点（不含病历正文，仅 ID/类型/接诊关闭状态）
        logger.info(
            "record.sign: submitted record_id=%s encounter_id=%s type=%s closed_encounter=%s",
            record.id, encounter_id, record_type, encounter_closed,
        )
        return record

    async def _paginate_records(
        self,
        *,
        filter_clauses: list,
        page: int,
        page_size: int,
        include_doctor_name: bool = False,
        include_patient_no: bool = False,
    ) -> dict:
        """list_by_doctor / list_by_patient 共用分页查询。

        SQL 查询次数：
          - 1 次 count（总条数）
          - 1 次主查询（病历+接诊+患者+visit_sequence+最新版本，全部 JOIN 一次返回）
          - 1 次 users 名字批量（include_doctor_name=True 时）
          总计 ≤ 3 次（旧实现每页 20 条 ≈ 40 次）。

        关键技术点：
          - visit_sequence：用 row_number() 窗口函数按 (patient_id, visit_type) 分区
            按 visited_at 升序排名，等价于"<= 当前 visited_at 的同组接诊数"。
          - 当前版本：用 LEFT JOIN + RecordVersion.version_no == MedicalRecord.current_version
            一次取回，消除原"循环里查 RecordVersion"的 N+1。
        """
        from app.models.patient import Patient

        offset = (page - 1) * page_size

        # ── 1. 总数 ──────────────────────────────────────────────────
        count_q = (
            select(func.count())
            .select_from(MedicalRecord)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .where(*filter_clauses)
        )
        total = (await self.db.execute(count_q)).scalar() or 0
        if total == 0:
            return {"total": 0, "items": []}

        # ── 2. 主查询 ──────────────────────────────────────────────────
        # 每个 encounter 在"同患者同 visit_type"序列里的序号子查询
        seq_subq = (
            select(
                Encounter.id.label("eid"),
                func.row_number().over(
                    partition_by=(Encounter.patient_id, Encounter.visit_type),
                    order_by=Encounter.visited_at.asc(),
                ).label("seq"),
            )
            .subquery()
        )
        # 主查询：病历 + 接诊 + 患者 + visit_sequence + 当前版本（LEFT JOIN）
        main_q = (
            select(MedicalRecord, Encounter, Patient, seq_subq.c.seq, RecordVersion)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .join(Patient, Encounter.patient_id == Patient.id)
            .join(seq_subq, seq_subq.c.eid == Encounter.id)
            .join(
                RecordVersion,
                and_(
                    RecordVersion.medical_record_id == MedicalRecord.id,
                    RecordVersion.version_no == MedicalRecord.current_version,
                ),
                isouter=True,
            )
            .where(*filter_clauses)
            .order_by(desc(MedicalRecord.submitted_at))
            .offset(offset)
            .limit(page_size)
        )
        rows = (await self.db.execute(main_q)).all()

        # ── 3. 医生名字批量 ───────────────────────────────────────────
        user_map: dict[str, str] = {}
        if include_doctor_name:
            from app.models.user import User
            doctor_ids: set[str] = set()
            for _, encounter, _, _, version in rows:
                if encounter.doctor_id:
                    doctor_ids.add(encounter.doctor_id)
                if version and version.triggered_by:
                    doctor_ids.add(version.triggered_by)
            if doctor_ids:
                user_rows = (await self.db.execute(
                    select(User.id, User.real_name).where(User.id.in_(doctor_ids))
                )).all()
                user_map = {uid: name for uid, name in user_rows}

        # ── 4. 组装 items ──────────────────────────────────────────────
        items = []
        for record, encounter, patient, visit_sequence, version in rows:
            # quick_save 格式 {"text": "..."} 取 text；其他格式作空串处理
            content_text = (
                version.content.get("text", "")
                if version and isinstance(version.content, dict) else ""
            )
            item = {
                "id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "submitted_at": record.submitted_at,
                "patient_name": patient.name,
                "patient_gender": patient.gender,
                # 患者年龄实时算（utils.calc_age 内含未过生日修正）
                "patient_age": calc_age(patient.birth_date),
                "encounter_id": encounter.id,
                # 前端历史病历列表需要用 is_first_visit 标"初诊/复诊"Tag
                "is_first_visit": encounter.is_first_visit,
                "visit_type": encounter.visit_type,
                # 同患者同 visit_type 下的就诊次序（1=初诊，2=复诊1，3=复诊2…）
                "visit_sequence": int(visit_sequence) if visit_sequence else 1,
                "content_preview": (
                    content_text[:80] + "..." if len(content_text) > 80 else content_text
                ),
                "content": content_text,
            }
            if include_patient_no:
                item["patient_no"] = patient.patient_no
            if include_doctor_name:
                # 接诊医生（接诊创建者）—— 前端详情页展示责任医生
                item["doctor_id"] = encounter.doctor_id
                item["doctor_name"] = (
                    user_map.get(encounter.doctor_id) if encounter.doctor_id else None
                )
                # 签发版本责任人（可能与接诊医生不同：如住院主管医生让管床医生代签发）
                item["submitted_by_id"] = version.triggered_by if version else None
                item["submitted_by_name"] = (
                    user_map.get(version.triggered_by)
                    if (version and version.triggered_by) else None
                )
            items.append(item)
        return {"total": total, "items": items}

    async def list_by_doctor(self, doctor_id: str, page: int = 1, page_size: int = 20) -> dict:
        """查询医生的历史签发病历列表（分页）。

        只返回 status='submitted' 的病历，按签发时间倒序排列。
        每条记录附带患者信息和病历内容预览（截取前 80 字）。
        """
        return await self._paginate_records(
            filter_clauses=[
                Encounter.doctor_id == doctor_id,
                MedicalRecord.status == "submitted",
            ],
            page=page,
            page_size=page_size,
        )

    async def list_by_patient(self, patient_id: str, page: int = 1, page_size: int = 30) -> dict:
        """查询某患者的全部已签发病历（不限医生），按签发时间倒序分页。

        任意登录医生都可查阅（同一患者初诊/复诊可能不同医生，复诊看历史是诊疗刚需）。
        审计日志在路由层写。

        每条返回含 `doctor_name`（接诊医生）+ `submitted_by_name`（签发版本责任人）
        + `submitted_at`，前端详情页据此显示"接诊医生 张三 · 签发于 ..."。
        """
        return await self._paginate_records(
            filter_clauses=[
                Encounter.patient_id == patient_id,
                MedicalRecord.status == "submitted",
            ],
            page=page,
            page_size=page_size,
            include_doctor_name=True,
            include_patient_no=True,
        )

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
