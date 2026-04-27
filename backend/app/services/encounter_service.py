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

from fastapi import HTTPException

from app.utils.age import calc_age
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.voice_record import VoiceRecord
from app.schemas.encounter import EncounterCreate, InquiryInputUpdate
from app.services.redis_cache import redis_cache

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
        if cached is not None:
            # 缓存里也存了 doctor_id，校验后返回，防止越权读到他人接诊
            if cached.get("_doctor_id") == doctor_id:
                # 返回时去掉内部字段
                return {k: v for k, v in cached.items() if k != "_doctor_id"}
            # doctor_id 不匹配（极少发生：同一 encounter_id 不同医生不可能同时进行中），
            # 走原始查询，404 由权限层抛
        encounter_result = await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))
            .where(Encounter.id == encounter_id, Encounter.doctor_id == doctor_id)
        )
        encounter = encounter_result.scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="接诊记录不存在或无权访问")

        # 取最新一条问诊输入（按 updated_at 倒序）
        inquiry_result = await self.db.execute(
            select(InquiryInput)
            .where(InquiryInput.encounter_id == encounter_id)
            .order_by(desc(InquiryInput.updated_at))
            .limit(1)
        )
        inquiry = inquiry_result.scalar_one_or_none()

        # 取所有病历记录（按更新时间/签发时间倒序，第一条为最新活跃病历）
        records_result = await self.db.execute(
            select(MedicalRecord)
            .where(MedicalRecord.encounter_id == encounter_id)
            .order_by(desc(MedicalRecord.updated_at), desc(MedicalRecord.submitted_at))
        )
        records = records_result.scalars().all()

        # 为每条病历加载当前版本内容
        record_items = []
        for record in records:
            version_result = await self.db.execute(
                select(RecordVersion)
                .where(
                    RecordVersion.medical_record_id == record.id,
                    RecordVersion.version_no == record.current_version,
                )
                .limit(1)
            )
            version = version_result.scalar_one_or_none()
            content = version.content if version else None

            # 内容格式兼容处理：
            # quick_save 格式：{"text": "病历全文"} → 直接取 text
            # 结构化格式：{"chief_complaint": ..., ...} → 按字段顺序重组为可读文本
            if isinstance(content, dict):
                if "text" in content:
                    content_text = content["text"]
                else:
                    _labels = {
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
                    parts = []
                    for key, label in _labels.items():
                        val = content.get(key, "")
                        if val:
                            parts.append(f"【{label}】\n{val}")
                    # 映射之外的字段追加到末尾
                    for key, val in content.items():
                        if key not in _labels and val:
                            parts.append(f"【{key}】\n{val}")
                    content_text = "\n\n".join(parts)
            elif isinstance(content, str):
                content_text = content
            else:
                content_text = ""

            record_items.append({
                "record_id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "current_version": record.current_version,
                "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
                "content": content_text,
            })

        active_record = record_items[0] if record_items else None

        # 最新语音录音（用于恢复语音工作区状态）
        voice_result = await self.db.execute(
            select(VoiceRecord)
            .where(VoiceRecord.encounter_id == encounter_id)
            .order_by(desc(VoiceRecord.updated_at), desc(VoiceRecord.created_at))
            .limit(1)
        )
        latest_voice = voice_result.scalar_one_or_none()

        # 患者年龄实时算（utils.calc_age 内含未过生日修正）
        patient = encounter.patient
        patient_age = calc_age(patient.birth_date) if patient else None

        # 患者档案（纵向持久数据）：JSONB 重构后统一走 PatientService.get_profile
        # 拿到扁平结构 + fields_meta（每字段 updated_at 用于前端展示"X 天前确认"）。
        # 月经史已不在档案里，需要的话从 inquiry_inputs.menstrual_history 取（snapshot.inquiry 已带）。
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
                "age": patient_age,
            } if patient else None,
            "patient_profile": patient_profile,
            "inquiry": {
                "chief_complaint": inquiry.chief_complaint or "",
                "history_present_illness": inquiry.history_present_illness or "",
                "past_history": inquiry.past_history or "",
                "allergy_history": inquiry.allergy_history or "",
                "personal_history": inquiry.personal_history or "",
                "physical_exam": inquiry.physical_exam or "",
                "initial_impression": inquiry.initial_impression or "",
                # 生命体征（结构化独立字段）
                "temperature": inquiry.temperature or "",
                "pulse": inquiry.pulse or "",
                "respiration": inquiry.respiration or "",
                "bp_systolic": inquiry.bp_systolic or "",
                "bp_diastolic": inquiry.bp_diastolic or "",
                "spo2": inquiry.spo2 or "",
                "height": inquiry.height or "",
                "weight": inquiry.weight or "",
                "marital_history": inquiry.marital_history or "",
                "menstrual_history": inquiry.menstrual_history or "",
                "family_history": inquiry.family_history or "",
                "history_informant": inquiry.history_informant or "",
                "current_medications": inquiry.current_medications or "",
                "rehabilitation_assessment": inquiry.rehabilitation_assessment or "",
                "religion_belief": inquiry.religion_belief or "",
                "pain_assessment": inquiry.pain_assessment or "",
                "vte_risk": inquiry.vte_risk or "",
                "nutrition_assessment": inquiry.nutrition_assessment or "",
                "psychology_assessment": inquiry.psychology_assessment or "",
                "auxiliary_exam": inquiry.auxiliary_exam or "",
                "admission_diagnosis": inquiry.admission_diagnosis or "",
                "tcm_inspection": inquiry.tcm_inspection or "",
                "tcm_auscultation": inquiry.tcm_auscultation or "",
                "tongue_coating": inquiry.tongue_coating or "",
                "pulse_condition": inquiry.pulse_condition or "",
                "western_diagnosis": inquiry.western_diagnosis or "",
                "tcm_disease_diagnosis": inquiry.tcm_disease_diagnosis or "",
                "tcm_syndrome_diagnosis": inquiry.tcm_syndrome_diagnosis or "",
                "treatment_method": inquiry.treatment_method or "",
                "treatment_plan": inquiry.treatment_plan or "",
                "followup_advice": inquiry.followup_advice or "",
                "precautions": inquiry.precautions or "",
                "observation_notes": inquiry.observation_notes or "",
                "patient_disposition": inquiry.patient_disposition or "",
                # 就诊时间：有记录则用记录值，否则从 encounter.visited_at 预填（便于首次生成病历时有时间戳）
                "visit_time": inquiry.visit_time or (
                    encounter.visited_at.strftime("%Y-%m-%d %H:%M") if encounter.visited_at else ""
                ),
                "onset_time": inquiry.onset_time or "",
                "version": inquiry.version,
            } if inquiry else None,
            "is_first_visit": encounter.is_first_visit,
            "active_record": active_record,    # 最新活跃病历（工作台直接显示）
            "records": record_items,            # 所有历史版本（供历史记录面板使用）
            "latest_voice_record": {
                "id": latest_voice.id,
                "status": latest_voice.status,
                "raw_transcript": latest_voice.raw_transcript or "",
                "transcript_summary": latest_voice.transcript_summary or "",
                "speaker_dialogue": latest_voice.get_speaker_dialogue(),
                "draft_record": latest_voice.draft_record or "",
            } if latest_voice else None,
        }
        # 缓存时附带 doctor_id 用于二次校验，防止其他医生命中别人的快照
        await redis_cache.set_json(
            cache_key,
            {**snapshot, "_doctor_id": doctor_id},
            ttl=_SNAPSHOT_TTL,
        )
        return snapshot

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
