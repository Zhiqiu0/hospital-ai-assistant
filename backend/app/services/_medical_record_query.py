"""病历列表查询 mixin（services/_medical_record_query.py）

从 medical_record_service 拆出（Round 5: 超标文件拆分）。含分页查询共用逻辑
（_paginate_records，一次 JOIN 消除 N+1 + 窗口函数算就诊次序）以及
按医生 / 按患者两个对外列表接口。由 MedicalRecordService 组合，依赖 self.db。
"""
from sqlalchemy import and_, desc, func, select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.utils.age import calc_age


class MedicalRecordQueryMixin:
    """病历列表查询（依赖宿主类提供 self.db）。"""

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
                # 病案首页快照：已签发病历必有，老病历可能为 None
                "patient_snapshot": record.patient_snapshot,
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
