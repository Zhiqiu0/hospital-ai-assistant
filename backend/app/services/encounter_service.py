"""
接诊服务（services/encounter_service.py）

职责：
  封装接诊记录的创建、查询及工作台快照组装：
  - create               : 新建接诊记录
  - get_my_encounters    : 获取当前医生进行中的接诊列表（最近 20 条）
  - get_by_id            : 按 ID 查询接诊（不存在时自动 404）
  - get_workspace_snapshot: 拼装工作台所需全量数据（患者/问诊/病历/语音）
  - save_inquiry         : 保存 / 更新问诊输入（自动版本号递增）

工作台快照（get_workspace_snapshot）设计说明：
  前端恢复接诊工作台时，需要一次性拿到所有相关数据，避免多次请求。
  此方法查询 encounter → patient → inquiry_input → medical_records → voice_record，
  组装成完整的 JSON 快照一次性返回。
"""

from typing import Any, Optional

from fastapi import HTTPException

from app.utils.age import calc_age
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.voice_record import VoiceRecord
from app.schemas.encounter import EncounterCreate, InquirySnapshot, InquiryInputUpdate
from app.services.redis_cache import redis_cache

# 病历内容字段标签（结构化 dict 内容回传前端时按此顺序拼成可读文本）
_RECORD_CONTENT_LABELS = {
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "physical_exam": "体格检查",
    "auxiliary_exam": "辅助检查",
    "initial_diagnosis": "初步诊断",
    "admission_diagnosis": "入院诊断",
    "treatment_plan": "诊疗计划",
}


def _parse_record_content(content: Any) -> str:
    """将 RecordVersion.content 三种存储形态统一序列化为可读文本。

    支持：
      - quick_save 格式：{"text": "病历全文"} → 直接取 text
      - 结构化格式：{"chief_complaint": ..., ...} → 按字段顺序拼成可读段落
      - 纯字符串：原样返回
      - None 或其他：返回空字符串
    """
    if isinstance(content, dict):
        if "text" in content:
            return content["text"] or ""
        parts: list[str] = []
        for key, label in _RECORD_CONTENT_LABELS.items():
            val = content.get(key, "")
            if val:
                parts.append(f"【{label}】\n{val}")
        # 映射之外的字段追加到末尾，避免新增字段静默丢失
        for key, val in content.items():
            if key not in _RECORD_CONTENT_LABELS and val:
                parts.append(f"【{key}】\n{val}")
        return "\n\n".join(parts)
    if isinstance(content, str):
        return content
    return ""


def _serialize_record(record: MedicalRecord, version: Optional[RecordVersion]) -> dict:
    """单条病历 → 工作台快照里的字典。"""
    return {
        "record_id": record.id,
        "record_type": record.record_type,
        "status": record.status,
        "current_version": record.current_version,
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "content": _parse_record_content(version.content if version else None),
    }


def _serialize_inquiry(inquiry: Optional[InquiryInput], encounter: Encounter) -> Optional[dict]:
    """问诊 ORM → 工作台快照字段字典。

    用 Pydantic 自动 None → ""（取代原 40+ 行手工 `or ""`）。
    visit_time 缺省时回退到 encounter.visited_at，便于首次生成病历时有时间戳。
    """
    if inquiry is None:
        return None
    data = InquirySnapshot.model_validate(inquiry).model_dump()
    if not data["visit_time"] and encounter.visited_at:
        data["visit_time"] = encounter.visited_at.strftime("%Y-%m-%d %H:%M")
    return data


def _serialize_voice(voice: Optional[VoiceRecord]) -> Optional[dict]:
    """最新一条语音录音 → 字典。"""
    if voice is None:
        return None
    return {
        "id": voice.id,
        "status": voice.status,
        "raw_transcript": voice.raw_transcript or "",
        "transcript_summary": voice.transcript_summary or "",
        "speaker_dialogue": voice.get_speaker_dialogue(),
        "draft_record": voice.draft_record or "",
    }

# Redis 缓存 key（snapshot 是 5+ 张表关联，是工作台启动热路径）
_SNAPSHOT_KEY = "encounter:snapshot:{eid}"
_SNAPSHOT_TTL = 60  # 60 秒，保存任意子数据时主动失效
_MY_ENCOUNTERS_KEY = "encounter:my:{doctor_id}"
_MY_ENCOUNTERS_TTL = 30


async def invalidate_encounter_snapshot(encounter_id: str) -> None:
    """保存 inquiry / 病历版本 / 语音 / 接诊状态变化后调用，失效 snapshot 缓存。

    放到模块级别是为了让其他 service（medical_record / voice / inpatient）
    能直接 import 失效，无需绕回 EncounterService 实例。
    """
    await redis_cache.delete(_SNAPSHOT_KEY.format(eid=encounter_id))


async def invalidate_my_encounters(doctor_id: str) -> None:
    """新建/关闭接诊后调用，失效"我的进行中接诊列表"缓存。"""
    await redis_cache.delete(_MY_ENCOUNTERS_KEY.format(doctor_id=doctor_id))


class EncounterService:
    """接诊服务：接诊记录的创建、查询和工作台数据组装。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: EncounterCreate, doctor_id: str) -> Encounter:
        """新建接诊记录，关联患者和当前医生。

        Args:
            data:      接诊创建入参（患者 ID、就诊类型等）。
            doctor_id: 接诊医生的用户 ID。

        Returns:
            新创建的 Encounter ORM 对象。
        """
        encounter = Encounter(
            patient_id=data.patient_id,
            doctor_id=doctor_id,
            department_id=data.department_id,
            visit_type=data.visit_type,
            is_first_visit=data.is_first_visit,
            bed_no=data.bed_no,
            admission_route=data.admission_route,
            admission_condition=data.admission_condition,
        )
        self.db.add(encounter)
        await self.db.commit()
        await self.db.refresh(encounter)
        # 新接诊会出现在该医生的进行中列表里，失效缓存
        await invalidate_my_encounters(doctor_id)
        # 住院接诊会改变患者的 has_active_inpatient 字段，失效该患者基本信息 + 搜索缓存
        if data.visit_type == "inpatient":
            from app.services.patient_service import _invalidate_patient_cache
            await _invalidate_patient_cache(data.patient_id)
        return encounter

    async def find_in_progress(self, patient_id: str, doctor_id: str):
        """查询该医生对该患者是否已有进行中的接诊，有则返回，无则返回 None。"""
        result = await self.db.execute(
            select(Encounter)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id == doctor_id,
                Encounter.status == "in_progress",
            )
            .order_by(Encounter.visited_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_my_encounters(self, doctor_id: str, limit: int = 20):
        """获取当前医生进行中的接诊列表（带 Redis 缓存 30s）。

        Args:
            doctor_id: 医生用户 ID。
            limit:     返回条数上限，默认 20。

        Returns:
            接诊列表，每项含接诊基本信息和患者概况。
        """
        # 列表是医生工作台首屏，每次切回都重读；新建/关闭接诊时主动失效
        cache_key = _MY_ENCOUNTERS_KEY.format(doctor_id=doctor_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None:
            return cached

        result = await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))  # 预加载患者，避免 N+1
            .where(Encounter.doctor_id == doctor_id, Encounter.status == "in_progress")
            .order_by(Encounter.visited_at.desc())
            .limit(limit)
        )
        encounters = result.scalars().all()
        data = [
            {
                "encounter_id": e.id,
                "visit_type": e.visit_type,
                "status": e.status,
                "visited_at": e.visited_at.isoformat() if e.visited_at else None,
                "chief_complaint_brief": e.chief_complaint_brief,
                "patient": {
                    "id": e.patient.id,
                    "name": e.patient.name,
                    "gender": e.patient.gender,
                    # 历史此处只用 year 相减，未减去未过生日的修正——
                    # 与 snapshot/详情接口算法不一致会让同一患者在不同页显示差 1 岁，
                    # 统一走 calc_age 顺带修复
                    "age": calc_age(e.patient.birth_date),
                } if e.patient else None,
            }
            for e in encounters
        ]
        await redis_cache.set_json(cache_key, data, ttl=_MY_ENCOUNTERS_TTL)
        return data

    async def get_by_id(self, encounter_id: str) -> Encounter:
        """按 ID 查询接诊记录。

        Raises:
            HTTPException(404): 接诊记录不存在。
        """
        result = await self.db.execute(select(Encounter).where(Encounter.id == encounter_id))
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="就诊记录不存在")
        return encounter

    async def get_workspace_snapshot(self, encounter_id: str, doctor_id: str) -> dict:
        """组装工作台完整快照（前端恢复接诊状态时调用）。

        查询内容：
          - Encounter（含 Patient）
          - 最新的 InquiryInput（问诊输入）
          - 所有 MedicalRecord（含最新版本内容）
          - 最新一条 VoiceRecord（语音录音）

        权限控制：
          只有接诊医生本人（doctor_id 匹配）才能访问，防止越权查看他人接诊。

        Raises:
            HTTPException(404): 接诊不存在或无权访问。

        缓存策略：
          5+ 张表关联，是工作台启动热路径。Redis 缓存 60s；保存 inquiry / 病历版本 /
          语音 / 接诊状态变化时由各 service 调 invalidate_encounter_snapshot 主动
          失效。注意：缓存 key 不带 doctor_id，但读时仍校验 doctor_id 才返回，
          避免把别的医生的快照当成命中。
        """
        cache_key = _SNAPSHOT_KEY.format(eid=encounter_id)
        cached = await redis_cache.get_json(cache_key)
        if cached is not None and cached.get("_doctor_id") == doctor_id:
            # 命中缓存且 doctor_id 校验通过，返回时剥掉内部字段
            return {k: v for k, v in cached.items() if k != "_doctor_id"}
        # 缓存未命中或 doctor_id 不匹配，走 DB 查询（404 由权限层抛）

        # ── 1. 接诊 + 患者（含权限校验）──────────────────────────────────
        encounter = (await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))
            .where(Encounter.id == encounter_id, Encounter.doctor_id == doctor_id)
        )).scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="接诊记录不存在或无权访问")

        # ── 2. 最新一条问诊输入（按 updated_at 倒序取 1 条）────────────
        inquiry = (await self.db.execute(
            select(InquiryInput)
            .where(InquiryInput.encounter_id == encounter_id)
            .order_by(desc(InquiryInput.updated_at))
            .limit(1)
        )).scalar_one_or_none()

        # ── 3. 病历 + 当前版本一次 LEFT JOIN 查回（消除 N+1）──────────
        # 原实现：N 条病历 → N+1 次查询；现在合并为 1 次。
        rows = (await self.db.execute(
            select(MedicalRecord, RecordVersion)
            .join(
                RecordVersion,
                and_(
                    RecordVersion.medical_record_id == MedicalRecord.id,
                    RecordVersion.version_no == MedicalRecord.current_version,
                ),
                isouter=True,
            )
            .where(MedicalRecord.encounter_id == encounter_id)
            .order_by(desc(MedicalRecord.updated_at), desc(MedicalRecord.submitted_at))
        )).all()
        record_items = [_serialize_record(record, version) for record, version in rows]

        # ── 4. 最新语音录音 ─────────────────────────────────────────────
        latest_voice = (await self.db.execute(
            select(VoiceRecord)
            .where(VoiceRecord.encounter_id == encounter_id)
            .order_by(desc(VoiceRecord.updated_at), desc(VoiceRecord.created_at))
            .limit(1)
        )).scalar_one_or_none()

        # ── 4.5 最新 AI 任务产物（QC issues + 追问/检查/诊断建议）────
        # 让 logout 重登 / 切设备时医生看到的不是空白，而是上次留下的 AI 产物
        latest_qc_issues, latest_ai_suggestions = await self._fetch_latest_ai_artifacts(encounter_id)

        # ── 5. 患者档案（PatientService.get_profile 内部 1 次查询）────
        # 延迟 import 避免 patient_service ↔ encounter_service 循环依赖。
        patient = encounter.patient
        patient_profile = None
        if patient:
            from app.services.patient_service import PatientService
            patient_profile = await PatientService(self.db).get_profile(patient.id)

        snapshot = {
            "encounter_id": encounter.id,
            "visit_type": encounter.visit_type,
            "status": encounter.status,
            "patient": {
                "id": patient.id,
                "name": patient.name,
                "gender": patient.gender,
                "age": calc_age(patient.birth_date),
            } if patient else None,
            "patient_profile": patient_profile,
            "inquiry": _serialize_inquiry(inquiry, encounter),
            "is_first_visit": encounter.is_first_visit,
            "active_record": record_items[0] if record_items else None,
            "records": record_items,
            "latest_voice_record": _serialize_voice(latest_voice),
            # ★ 治本：把 AI 产物也带回去——logout 重登不丢质控/追问/检查/诊断
            "latest_qc_issues": latest_qc_issues,
            "latest_ai_suggestions": latest_ai_suggestions,
        }
        # 缓存附带 doctor_id 做二次校验，防止越权命中他人快照
        await redis_cache.set_json(
            cache_key,
            {**snapshot, "_doctor_id": doctor_id},
            ttl=_SNAPSHOT_TTL,
        )
        return snapshot

    async def _fetch_latest_ai_artifacts(
        self, encounter_id: str
    ) -> tuple[list[dict], dict]:
        """取该接诊最新一次 QC issues + 各类 AI 建议（追问/检查/诊断）。

        - QC：取最新一条 task_type='qc' 的 ai_task 关联的全部 qc_issues
        - 建议：按 task_type 各取最新一条 ai_task 的 output_result
                  inquiry / exam / diagnosis 三类各一份

        让 logout 重登 / 切设备 / 浏览器崩溃后医生仍能拿到上次跑的产物，
        不用重跑 LLM（省 token + 体验丝滑）。

        Returns:
            (qc_issues_list, ai_suggestions_dict)
            qc_issues_list 形如 [{"field_name":..., "issue_description":..., ...}]
            ai_suggestions_dict 形如 {"inquiry": {...}, "exam": {...}, "diagnosis": {...}}
            缺数据用空 list / 空 dict，前端能直接灌进 store
        """
        from app.models.medical_record import AITask, QCIssue
        # 最新 QC task
        latest_qc_task = (await self.db.execute(
            select(AITask)
            .where(AITask.encounter_id == encounter_id, AITask.task_type == "qc")
            .order_by(desc(AITask.created_at))
            .limit(1)
        )).scalar_one_or_none()
        qc_issues_list: list[dict] = []
        if latest_qc_task:
            issues = (await self.db.execute(
                select(QCIssue).where(QCIssue.ai_task_id == latest_qc_task.id)
            )).scalars().all()
            qc_issues_list = [
                {
                    "source": i.source,
                    "issue_type": i.issue_type,
                    "risk_level": i.risk_level,
                    "field_name": i.field_name,
                    "issue_description": i.issue_description,
                    "suggestion": i.suggestion,
                }
                for i in issues
            ]

        # 各类建议：按 task_type 各取最新一条
        ai_suggestions: dict = {}
        for task_type, key in [("inquiry", "inquiry"), ("exam", "exam"), ("diagnosis", "diagnosis")]:
            task = (await self.db.execute(
                select(AITask)
                .where(AITask.encounter_id == encounter_id, AITask.task_type == task_type)
                .order_by(desc(AITask.created_at))
                .limit(1)
            )).scalar_one_or_none()
            if task and task.output_result:
                ai_suggestions[key] = task.output_result

        return qc_issues_list, ai_suggestions

    async def save_inquiry(self, encounter_id: str, data: InquiryInputUpdate):
        """保存或更新问诊输入（upsert 逻辑，自动版本号递增）。

        逻辑：
          - 存在 InquiryInput → 更新已有字段，version += 1
          - 不存在 → 创建新记录，version 从 1 开始

        Returns:
            包含保存成功信息和更新后版本号的字典。
        """
        result = await self.db.execute(
            select(InquiryInput).where(InquiryInput.encounter_id == encounter_id)
        )
        inquiry = result.scalar_one_or_none()

        if inquiry:
            # 只更新传入的非 None 字段（None 表示"不修改"）
            for field, value in data.model_dump(exclude_none=True).items():
                setattr(inquiry, field, value)
            inquiry.version += 1
        else:
            inquiry = InquiryInput(
                encounter_id=encounter_id,
                **data.model_dump(exclude_none=True),
            )
            self.db.add(inquiry)

        await self.db.commit()
        await self.db.refresh(inquiry)
        # 失效 snapshot 缓存：问诊改了，下次进工作台必须重新拼装
        await invalidate_encounter_snapshot(encounter_id)
        return {
            "message": "保存成功",
            "version": inquiry.version,
            "chief_complaint": inquiry.chief_complaint,
            "history_present_illness": inquiry.history_present_illness,
        }
