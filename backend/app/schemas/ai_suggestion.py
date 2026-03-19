from pydantic import BaseModel
from typing import Optional


class InquirySuggestionRequest(BaseModel):
    chief_complaint: str
    history_present_illness: Optional[str] = None
    department: Optional[str] = None
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None


class ExamSuggestionRequest(BaseModel):
    chief_complaint: str
    history_present_illness: Optional[str] = None
    initial_impression: Optional[str] = None
    department: Optional[str] = None
