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
    # onset_time（2026-08-20 复诊走查补）：复诊是同一病程，病发时间延续上次；
    # 此前不在清单里 → 复诊必填的病发时间恒空，保存被校验拦住
    "onset_time",
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

        Raises:
            HTTPException 403: 病历已签发（门急诊）/ 已出院（住院）后不得再改。
        """
        # ── 签发冻结守卫（2026-09-01 数据更正流程审计）────────────────────
        # 为什么必须有：HIS 回写的 payload 里 record.* / vitals.* 不是从签发正文里
        # 抄的，而是**推送那一刻从 InquiryInput 实时重建**（his_adapter/
        # writeback_builder.py）。而 sign_hash 只覆盖病历正文与患者快照，**不覆盖
        # 结构化问诊字段**。于是签发后改这里会造成两个后果：
        #   ① 我方签发件写着血压 180/85（进了哈希、锁死），HIS 病案（医院的法定
        #      病案）在任何一次对账补投或管理员修订重推后拿到 130/85——两边永久
        #      不一致，而 /admin/records/signature-integrity 仍显示"全部通过"；
        #   ② 这等于一条**绕过防篡改体系的写通道**：改不了正文，但能改被回写出去
        #      的结构化数据。
        # 病历草稿（_medical_record_draft）和诊断条目（diagnosis_service）早就有
        # 这道守卫，唯独问诊输入漏了。口径逐字照抄诊断那边，避免三处各有各的说法：
        #   门急诊：一次接诊一份病历，已签发即冻结
        #   住院：多文书持续录入，出院（encounter completed）后才冻结
        from fastapi import HTTPException

        from app.models.encounter import Encounter
        from app.models.medical_record import MedicalRecord
        enc = await self.db.get(Encounter, encounter_id)
        if enc is not None:
            if enc.visit_type == "inpatient":
                if enc.status == "completed":
                    raise HTTPException(
                        status_code=403, detail="已出院，问诊与体征数据不可再修改")
            else:
                signed = (await self.db.execute(
                    select(MedicalRecord.id).where(
                        MedicalRecord.encounter_id == encounter_id,
                        MedicalRecord.status == "submitted",
                    ).limit(1)
                )).scalar_one_or_none()
                if signed is not None:
                    raise HTTPException(
                        status_code=403,
                        detail="病历已签发，问诊与体征数据不可再修改"
                               "（如需更正请走病历修订通道）")

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
