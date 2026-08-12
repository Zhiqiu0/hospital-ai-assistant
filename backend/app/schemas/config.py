"""
配置类 Schema（app/schemas/config.py）

包含：
  PromptTemplate — 自定义 Prompt 模板（Create / Update / Response）

历史说明（2026-08-12 清理）：QCRule 三个 schema 已随 /admin/qc-rules 旧只读端点
删除——评分标准由 qc_engine.rubrics 代码常量驱动（/admin/rubrics 展示），
qc_rules 表仅剩医保规则引擎在读（不走本 schema）。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from pydantic import BaseModel


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
