from sqlalchemy import String, Boolean, Date
from sqlalchemy.orm import mapped_column, Mapped, relationship
from typing import Optional
import datetime
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    patient_no: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(String(10))
    birth_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    id_card: Mapped[Optional[str]] = mapped_column(String(20))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(String)
    is_from_his: Mapped[bool] = mapped_column(Boolean, default=False)
    # 病案首页扩展字段
    ethnicity: Mapped[Optional[str]] = mapped_column(String(20))
    marital_status: Mapped[Optional[str]] = mapped_column(String(10))
    occupation: Mapped[Optional[str]] = mapped_column(String(100))
    workplace: Mapped[Optional[str]] = mapped_column(String(200))
    contact_name: Mapped[Optional[str]] = mapped_column(String(50))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    contact_relation: Mapped[Optional[str]] = mapped_column(String(20))
    blood_type: Mapped[Optional[str]] = mapped_column(String(10))

    encounters: Mapped[list["Encounter"]] = relationship(back_populates="patient")


from app.models.encounter import Encounter
