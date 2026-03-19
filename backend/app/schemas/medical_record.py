from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class MedicalRecordCreate(BaseModel):
    encounter_id: str
    record_type: str


class RecordGenerateRequest(BaseModel):
    inquiry_input: dict


class RecordContinueRequest(BaseModel):
    current_content: dict
    target_field: str


class RecordPolishRequest(BaseModel):
    content: dict
    target_fields: Optional[list[str]] = None


class RecordContentUpdate(BaseModel):
    content: dict


class MedicalRecordResponse(BaseModel):
    id: str
    encounter_id: str
    record_type: str
    status: str
    current_version: int
    created_at: datetime

    class Config:
        from_attributes = True
