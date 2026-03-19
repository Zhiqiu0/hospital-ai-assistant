from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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
