from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class LabReport(Base, TimestampMixin):
    """检验报告表"""
    __tablename__ = "lab_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    doctor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[Optional[str]] = mapped_column(String(300))
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    # AI OCR 识别出的结构化文本
    ocr_text: Mapped[Optional[str]] = mapped_column(Text)
    # uploaded | analyzing | done | failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    doctor: Mapped[Optional["User"]] = relationship(foreign_keys=[doctor_id])


from app.models.user import User  # noqa: E402, F401
