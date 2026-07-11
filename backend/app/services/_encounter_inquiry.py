"""问诊输入保存 + 同步上次病历 mixin（services/_encounter_inquiry.py）

从 encounter_service 拆出（Round: 超标文件拆分）。由 EncounterService 组合。
"""
from fastapi import HTTPException
from sqlalchemy import desc, select

from app.models.encounter import Encounter, InquiryInput
from app.schemas.encounter import InquiryInputUpdate
from app.services.encounter_cache import invalidate_encounter_snapshot

# 一键同步上次病历：可复制的「文字病历」字段。
#   - 体征数值不带回——本次需重新测量，守数值真实性；
#   - 时间字段（visit_time/onset_time）不带回——它们是本次就诊特有的结构化字段，
#     前端用 DatePicker（需 dayjs 对象），把上次的字符串塞进去会让 antd DatePicker
#     崩溃（date.isValid is not a function）。故此列表只含纯文本字段。
_SYNC_COPY_FIELDS = [
    "chief_complaint", "history_present_illness", "past_history",
    "allergy_history", "personal_history", "current_medications", "history_informant",
    "family_history", "marital_history", "menstrual_history", "physical_exam",
    "auxiliary_exam", "initial_impression", "tcm_inspection", "tcm_auscultation",
    "tongue_coating", "pulse_condition", "western_diagnosis", "tcm_disease_diagnosis",
    "tcm_syndrome_diagnosis", "treatment_method", "treatment_plan", "followup_advice",
    "precautions", "observation_notes", "patient_disposition", "admission_diagnosis",
    "rehabilitation_assessment", "religion_belief", "pain_assessment", "vte_risk",
    "nutrition_assessment", "psychology_assessment",
]


class EncounterInquiryMixin:
    """问诊保存 + 同步上次病历（依赖宿主类提供 self.db）。"""

    async def get_previous_record(self, encounter_id: str) -> dict:
        """一键同步上次病历：取该患者上一次接诊的病历文字字段（供复诊参考）。

        慢性病复诊每次病历大同小异，把上次的文字病历一键带过来省得重打。
        体征数值（体温/血压/心率等）不带回——本次是新测量，不能沿用上次
        （数值真实性：不得把上次的测量值当本次的）。

        Returns:
            {"source_encounter_id": 上次接诊ID或None,
             "source_visit_time": 上次就诊时间或None,
             "fields": {字段: 值}}（只含非空文字字段；无历史时 fields 为空 dict）
        """
        encounter = await self.db.get(Encounter, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=404, detail="接诊不存在")
        # 该患者最近一次「其它」接诊的最新问诊
        # 排除 cancelled 接诊：已取消的接诊在业务上「没发生过」，不能当复诊参考带回。
        prev = (await self.db.execute(
            select(InquiryInput)
            .join(Encounter, InquiryInput.encounter_id == Encounter.id)
            .where(
                Encounter.patient_id == encounter.patient_id,
                Encounter.id != encounter_id,
                Encounter.status != "cancelled",
            )
            .order_by(desc(InquiryInput.created_at))
            .limit(1)
        )).scalar_one_or_none()
        if prev is None:
            return {"source_encounter_id": None, "source_visit_time": None, "fields": {}}
        fields = {f: getattr(prev, f) for f in _SYNC_COPY_FIELDS if getattr(prev, f, None)}
        return {
            "source_encounter_id": prev.encounter_id,
            "source_visit_time": prev.visit_time,
            "fields": fields,
        }

    async def save_inquiry(self, encounter_id: str, data: InquiryInputUpdate):
        """保存或更新问诊输入（upsert 逻辑，自动版本号递增）。

        逻辑：
          - 存在 InquiryInput → 更新已有字段，version += 1
          - 不存在 → 创建新记录，version 从 1 开始

        Returns:
            包含保存成功信息和更新后版本号的字典。
        """
        # (encounter_id) 无唯一约束，并发首次保存可能各插一条造成多行；
        # 读侧一律 order_by+取最新，这里也必须一致——
        # 不能用 scalar_one_or_none()，多行会抛 MultipleResultsFound 让此后每次保存都 500。
        result = await self.db.execute(
            select(InquiryInput)
            .where(InquiryInput.encounter_id == encounter_id)
            .order_by(desc(InquiryInput.updated_at))
        )
        inquiry = result.scalars().first()

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
