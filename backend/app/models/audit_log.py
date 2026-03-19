from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import mapped_column, Mapped
from typing import Optional
from app.database import Base
from app.models.base import generate_uuid


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=func.now())

    # Who did it
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_role: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # What was done
    action: Mapped[str] = mapped_column(String(50))          # e.g. create_record, qc_run, login
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # patient / record / user
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Request context
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ok")  # ok / error
