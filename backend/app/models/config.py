from sqlalchemy import String, Boolean, Text
from sqlalchemy.orm import mapped_column, Mapped
from typing import Optional
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class QCRule(Base, TimestampMixin):
    __tablename__ = "qc_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    rule_type: Mapped[Optional[str]] = mapped_column(String(30))  # completeness/format/logic
    field_name: Mapped[Optional[str]] = mapped_column(String(50))
    condition: Mapped[Optional[str]] = mapped_column(String(200))
    risk_level: Mapped[Optional[str]] = mapped_column(String(10))  # high/medium/low
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ModelConfig(Base, TimestampMixin):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    scene: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)   # generate/polish/qc/inquiry/exam
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="deepseek-chat")
    temperature: Mapped[float] = mapped_column(default=0.3)
    max_tokens: Mapped[int] = mapped_column(default=4096)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scene: Mapped[Optional[str]] = mapped_column(String(50))  # generate/polish/qc/inquiry
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="v1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
