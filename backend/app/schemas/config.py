from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class QCRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    rule_type: Optional[str] = None
    field_name: Optional[str] = None
    condition: Optional[str] = None
    risk_level: Optional[str] = None


class QCRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    field_name: Optional[str] = None
    condition: Optional[str] = None
    risk_level: Optional[str] = None
    is_active: Optional[bool] = None


class QCRuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    rule_type: Optional[str] = None
    field_name: Optional[str] = None
    condition: Optional[str] = None
    risk_level: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromptTemplateCreate(BaseModel):
    name: str
    scene: Optional[str] = None
    content: str
    version: Optional[str] = "v1"


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    scene: Optional[str] = None
    content: Optional[str] = None
    version: Optional[str] = None
    is_active: Optional[bool] = None


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    scene: Optional[str] = None
    content: str
    version: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
