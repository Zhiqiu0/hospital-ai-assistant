"""
AI 接口请求模型（Request Schemas）

所有 /api/v1/ai/* 端点的入参 Pydantic 模型。
按功能分组：病历生成、质控、问诊/检查/诊断建议、语音结构化。
"""

from typing import Optional

from pydantic import BaseModel


# ── 病历生成 ───────────────────────────────────────────────────────────────────

class QuickGenerateRequest(BaseModel):
    """快速生成病历的入参，覆盖门诊/急诊/住院全部字段。"""

    # 基础问诊
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    personal_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    initial_impression: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""

    # 病历类型与就诊性质
    record_type: Optional[str] = "outpatient"
    visit_type_detail: Optional[str] = "outpatient"
    is_first_visit: Optional[bool] = True

    # 患者基本信息
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""

    # 时间
    visit_time: Optional[str] = ""
    onset_time: Optional[str] = ""

    # 住院专项评估
    history_informant: Optional[str] = ""
    marital_history: Optional[str] = ""
    menstrual_history: Optional[str] = ""
    family_history: Optional[str] = ""
    current_medications: Optional[str] = ""
    pain_assessment: Optional[str] = ""
    vte_risk: Optional[str] = ""
    nutrition_assessment: Optional[str] = ""
    psychology_assessment: Optional[str] = ""
    rehabilitation_assessment: Optional[str] = ""
    religion_belief: Optional[str] = ""

    # 门诊中医四诊
    tcm_inspection: Optional[str] = ""
    tcm_auscultation: Optional[str] = ""
    tongue_coating: Optional[str] = ""
    pulse_condition: Optional[str] = ""

    # 门诊诊断细化
    western_diagnosis: Optional[str] = ""
    tcm_disease_diagnosis: Optional[str] = ""
    tcm_syndrome_diagnosis: Optional[str] = ""

    # 治疗意见
    treatment_method: Optional[str] = ""
    treatment_plan: Optional[str] = ""
    followup_advice: Optional[str] = ""
    precautions: Optional[str] = ""

    # 急诊附加
    observation_notes: Optional[str] = ""
    patient_disposition: Optional[str] = ""


class ContinueRequest(BaseModel):
    """续写病历的入参。"""

    current_content: str = ""
    record_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    personal_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    initial_impression: Optional[str] = ""


class SupplementRequest(BaseModel):
    """根据质控问题补全病历的入参。"""

    current_content: str = ""
    qc_issues: Optional[list] = []
    record_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    personal_history: Optional[str] = ""
    family_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    initial_impression: Optional[str] = ""
    onset_time: Optional[str] = ""
    visit_time: Optional[str] = ""


class PolishRequest(BaseModel):
    """润色病历的入参。"""

    content: str = ""


class NormalizeFieldsRequest(BaseModel):
    """规范化问诊字段（口语→书面）的入参。"""

    fields: dict  # {field_name: value}


# ── 语音结构化 ─────────────────────────────────────────────────────────────────

class VoiceStructureRequest(BaseModel):
    """语音转写结构化的入参。"""

    transcript: str = ""
    transcript_id: Optional[str] = None
    visit_type: Optional[str] = "outpatient"
    patient_name: Optional[str] = ""
    patient_gender: Optional[str] = ""
    patient_age: Optional[str] = ""
    existing_inquiry: Optional[dict] = None


# ── 问诊 / 检查 / 诊断建议 ────────────────────────────────────────────────────

class InquirySuggestionsRequest(BaseModel):
    """问诊追问建议的入参。"""

    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    initial_impression: Optional[str] = ""


class ExamSuggestionsRequest(BaseModel):
    """辅助检查建议的入参。"""

    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    initial_impression: Optional[str] = ""
    department: Optional[str] = ""


class DiagnosisSuggestionRequest(BaseModel):
    """诊断建议的入参。"""

    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    initial_impression: Optional[str] = ""
    inquiry_answers: Optional[list] = []  # [{"question": "...", "answer": "..."}]


# ── 质控（QC）─────────────────────────────────────────────────────────────────

class QuickQCRequest(BaseModel):
    """快速质控的入参，覆盖门诊/住院全部检查字段。"""

    content: str = ""
    record_type: Optional[str] = "outpatient"
    encounter_id: Optional[str] = None
    is_first_visit: Optional[bool] = True

    # 基础问诊字段（用于规则引擎）
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    physical_exam: Optional[str] = ""

    # 住院专项评估字段
    marital_history: Optional[str] = ""
    family_history: Optional[str] = ""
    pain_assessment: Optional[str] = ""
    vte_risk: Optional[str] = ""
    nutrition_assessment: Optional[str] = ""
    psychology_assessment: Optional[str] = ""
    rehabilitation_assessment: Optional[str] = ""
    current_medications: Optional[str] = ""
    religion_belief: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    admission_diagnosis: Optional[str] = ""

    # 门诊中医四诊及治疗字段
    tcm_inspection: Optional[str] = ""
    tcm_auscultation: Optional[str] = ""
    tongue_coating: Optional[str] = ""
    pulse_condition: Optional[str] = ""
    western_diagnosis: Optional[str] = ""
    tcm_disease_diagnosis: Optional[str] = ""
    tcm_syndrome_diagnosis: Optional[str] = ""
    treatment_method: Optional[str] = ""
    treatment_plan: Optional[str] = ""
    followup_advice: Optional[str] = ""
    precautions: Optional[str] = ""
    onset_time: Optional[str] = ""


class QCFixRequest(BaseModel):
    """质控修复建议的入参。"""

    field_name: Optional[str] = ""
    issue_description: Optional[str] = ""
    suggestion: Optional[str] = ""
    current_record: Optional[str] = ""
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""


class GradeScoreRequest(BaseModel):
    """甲级病历评分的入参。"""

    content: str = ""
    record_type: Optional[str] = "admission_note"

    # 住院问诊字段（供规则引擎使用）
    chief_complaint: Optional[str] = ""
    history_present_illness: Optional[str] = ""
    past_history: Optional[str] = ""
    allergy_history: Optional[str] = ""
    physical_exam: Optional[str] = ""
    marital_history: Optional[str] = ""
    family_history: Optional[str] = ""
    pain_assessment: Optional[str] = ""
    vte_risk: Optional[str] = ""
    nutrition_assessment: Optional[str] = ""
    psychology_assessment: Optional[str] = ""
    rehabilitation_assessment: Optional[str] = ""
    current_medications: Optional[str] = ""
    religion_belief: Optional[str] = ""
    auxiliary_exam: Optional[str] = ""
    admission_diagnosis: Optional[str] = ""
