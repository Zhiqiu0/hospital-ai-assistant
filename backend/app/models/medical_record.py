from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped, relationship
from typing import Optional, Any
from datetime import datetime
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class MedicalRecord(Base, TimestampMixin):
    __tablename__ = "medical_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), nullable=False)
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    encounter: Mapped["Encounter"] = relationship(back_populates="medical_records")
    versions: Mapped[list["RecordVersion"]] = relationship(back_populates="record")
    qc_issues: Mapped[list["QCIssue"]] = relationship(back_populates="record")


class RecordVersion(Base):
    __tablename__ = "record_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    medical_record_id: Mapped[str] = mapped_column(ForeignKey("medical_records.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[Any] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    ai_task_id: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    record: Mapped[MedicalRecord] = relationship(back_populates="versions")


class QCIssue(Base):
    __tablename__ = "qc_issues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    ai_task_id: Mapped[str] = mapped_column(ForeignKey("ai_tasks.id"), nullable=False)
    medical_record_id: Mapped[Optional[str]] = mapped_column(ForeignKey("medical_records.id"), nullable=True)
    record_version_no: Mapped[Optional[int]] = mapped_column(Integer)
    issue_type: Mapped[str] = mapped_column(String(30), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(50))
    issue_description: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    source: Mapped[str] = mapped_column(String(10), default="rule")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    record: Mapped[Optional["MedicalRecord"]] = relationship(back_populates="qc_issues")


class AITask(Base):
    __tablename__ = "ai_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    medical_record_id: Mapped[Optional[str]] = mapped_column(ForeignKey("medical_records.id"))
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    input_snapshot: Mapped[Optional[Any]] = mapped_column(JSONB)
    output_result: Mapped[Optional[Any]] = mapped_column(JSONB)
    model_name: Mapped[Optional[str]] = mapped_column(String(50))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20))
    token_input: Mapped[Optional[int]] = mapped_column(Integer)
    token_output: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


from app.models.encounter import Encounter  # noqa: E402
