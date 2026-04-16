"""
配置类 Schema（app/schemas/config.py）

包含：
  QCRule         — 质控规则（Create / Update / Response）
  PromptTemplate — 自定义 Prompt 模板（Create / Update / Response）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime
from typing import List, Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from pydantic import BaseModel


class QCRuleCreate(BaseModel):
    rule_code: str
    name: str
    description: Optional[str] = None
    rule_type: str  # completeness / insurance
    scope: Optional[str] = "all"  # all / inpatient / revisit / tcm
    field_name: Optional[str] = None
    keywords: Optional[List[str]] = None
    indication_keywords: Optional[List[str]] = None
    risk_level: Optional[str] = "medium"
    issue_description: Optional[str] = None
    suggestion: Optional[str] = None
    score_impact: Optional[str] = None


class QCRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    scope: Optional[str] = None
    field_name: Optional[str] = None
    keywords: Optional[List[str]] = None
    indication_keywords: Optional[List[str]] = None
    risk_level: Optional[str] = None
    issue_description: Optional[str] = None
    suggestion: Optional[str] = None
    score_impact: Optional[str] = None
    is_active: Optional[bool] = None


class QCRuleResponse(BaseModel):
    id: str
    rule_code: str
    name: str
    description: Optional[str] = None
    rule_type: str
    scope: str
    field_name: Optional[str] = None
    keywords: Optional[List[str]] = None
    indication_keywords: Optional[List[str]] = None
    risk_level: str
    issue_description: Optional[str] = None
    suggestion: Optional[str] = None
    score_impact: Optional[str] = None
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
