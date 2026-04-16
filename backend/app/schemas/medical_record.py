"""
病历相关 Pydantic 模型（Medical Record Schemas）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime
from typing import Any, Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class QuickSaveRequest(BaseModel):
    """签发时快速保存病历的入参。"""

    encounter_id: str
    record_type: str = "outpatient"
    content: str


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
