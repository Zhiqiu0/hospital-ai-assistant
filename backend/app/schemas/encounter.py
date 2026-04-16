"""
接诊相关 Pydantic 模型（Encounter Schemas）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class QuickStartRequest(BaseModel):
    """一键开始接诊：自动创建患者（如有需要）并创建接诊记录。"""

    patient_name: str
    gender: Optional[str] = "unknown"
    age: Optional[int] = None
    birth_date: Optional[str] = None          # YYYY-MM-DD
    id_card: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    ethnicity: Optional[str] = None
    marital_status: Optional[str] = None
    occupation: Optional[str] = None
    workplace: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    blood_type: Optional[str] = None
    visit_type: str = "outpatient"
    department_id: Optional[str] = None
    bed_no: Optional[str] = None
    admission_route: Optional[str] = None
    admission_condition: Optional[str] = None


class EncounterCreate(BaseModel):
    patient_id: str
    visit_type: str
    department_id: Optional[str] = None
    is_first_visit: bool = True
    bed_no: Optional[str] = None
    admission_route: Optional[str] = None
    admission_condition: Optional[str] = None


class InquiryInputUpdate(BaseModel):
    chief_complaint: Optional[str] = None
    history_present_illness: Optional[str] = None
    past_history: Optional[str] = None
    allergy_history: Optional[str] = None
    personal_history: Optional[str] = None
    physical_exam: Optional[str] = None
    initial_impression: Optional[str] = None
    # 住院部扩展字段
    marital_history: Optional[str] = None
    menstrual_history: Optional[str] = None
    family_history: Optional[str] = None
    history_informant: Optional[str] = None
    current_medications: Optional[str] = None
    rehabilitation_assessment: Optional[str] = None
    religion_belief: Optional[str] = None
    pain_assessment: Optional[str] = None
    vte_risk: Optional[str] = None
    nutrition_assessment: Optional[str] = None
    psychology_assessment: Optional[str] = None
    auxiliary_exam: Optional[str] = None
    admission_diagnosis: Optional[str] = None
    # 门诊中医四诊
    tcm_inspection: Optional[str] = None
    tcm_auscultation: Optional[str] = None
    tongue_coating: Optional[str] = None
    pulse_condition: Optional[str] = None
    # 门诊诊断细化
    western_diagnosis: Optional[str] = None
    tcm_disease_diagnosis: Optional[str] = None
    tcm_syndrome_diagnosis: Optional[str] = None
    # 治疗意见
    treatment_method: Optional[str] = None
    treatment_plan: Optional[str] = None
    followup_advice: Optional[str] = None
    precautions: Optional[str] = None
    # 急诊附加
    observation_notes: Optional[str] = None
    patient_disposition: Optional[str] = None
    # 时间
    visit_time: Optional[str] = None
    onset_time: Optional[str] = None


class EncounterResponse(BaseModel):
    id: str
    patient_id: str
    visit_type: str
    status: str
    is_first_visit: bool
    visited_at: datetime
    department_id: Optional[str] = None

    class Config:
        from_attributes = True
