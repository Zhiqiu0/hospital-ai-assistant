"""
配置类模型（app/models/config.py）

包含：
  QCRule         — 质控规则（DB 驱动，规则引擎从此表读取）
  ModelConfig    — AI 场景模型配置
  PromptTemplate — 自定义 Prompt 模板
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class QCRule(Base, TimestampMixin):
    """质控规则。

    规则引擎执行逻辑：
      - rule_type='completeness' : 检查 keywords 列表中任一关键词是否出现在病历文本中；未出现则触发
      - rule_type='insurance'    : 检查 keywords 中的触发词是否出现；出现后若附近无 indication_keywords
                                   中的适应症词则触发（indication_keywords 为空时只要触发词出现即报警）

    scope 字段控制规则应用范围：
      - all       : 所有病历
      - inpatient : 仅住院病历
      - revisit   : 仅复诊病历
      - tcm       : 仅含中医内容的病历（病历文本中检测到中医关键词）

    gender_scope 字段控制性别限制：
      - all    : 不限性别
      - female : 仅女性患者触发（如月经史）
      - male   : 仅男性患者触发
    """

    __tablename__ = "qc_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    rule_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # 规则类型：completeness（完整性） / insurance（医保风险）
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 适用范围：all / inpatient / revisit / tcm
    scope: Mapped[str] = mapped_column(String(20), default="all", nullable=False)
    # 性别限制：all / female / male（如月经史只对女性触发）
    gender_scope: Mapped[str] = mapped_column(String(10), default="all", nullable=False)

    field_name: Mapped[Optional[str]] = mapped_column(String(50))

    # 关键词列表（JSON 数组）：任一关键词出现视为该字段已填写
    keywords: Mapped[Optional[list]] = mapped_column(JSON)
    # 适应症词列表（JSON 数组，仅 insurance 规则使用）：附近出现这些词则不报警
    indication_keywords: Mapped[Optional[list]] = mapped_column(JSON)

    risk_level: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    issue_description: Mapped[Optional[str]] = mapped_column(Text)
    suggestion: Mapped[Optional[str]] = mapped_column(Text)
    score_impact: Mapped[Optional[str]] = mapped_column(String(20))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ModelConfig(Base, TimestampMixin):
    """AI 场景模型配置（按场景覆盖全局默认模型参数）。"""

    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    scene: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="deepseek-chat")
    temperature: Mapped[float] = mapped_column(default=0.3)
    max_tokens: Mapped[int] = mapped_column(default=4096)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class PromptTemplate(Base, TimestampMixin):
    """自定义 Prompt 模板（激活后覆盖代码内置默认 prompt）。"""

    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scene: Mapped[Optional[str]] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="v1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
