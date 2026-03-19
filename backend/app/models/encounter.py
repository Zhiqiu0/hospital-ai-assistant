from sqlalchemy import String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import mapped_column, Mapped, relationship
from typing import Optional
from datetime import datetime
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Encounter(Base, TimestampMixin):
    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))
    visit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    visit_no: Mapped[Optional[str]] = mapped_column(String(50))
    is_first_visit: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    chief_complaint_brief: Mapped[Optional[str]] = mapped_column(String(200))
    visited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    bed_no: Mapped[Optional[str]] = mapped_column(String(20))
    admission_route: Mapped[Optional[str]] = mapped_column(String(20))
    admission_condition: Mapped[Optional[str]] = mapped_column(String(10))

    patient: Mapped["Patient"] = relationship(back_populates="encounters")
    medical_records: Mapped[list["MedicalRecord"]] = relationship(back_populates="encounter")
    inquiry_inputs: Mapped[list["InquiryInput"]] = relationship(back_populates="encounter")


class InquiryInput(Base, TimestampMixin):
    __tablename__ = "inquiry_inputs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[str] = mapped_column(ForeignKey("encounters.id"), nullable=False)
    chief_complaint: Mapped[Optional[str]] = mapped_column(Text)
    history_present_illness: Mapped[Optional[str]] = mapped_column(Text)
    past_history: Mapped[Optional[str]] = mapped_column(Text)
    allergy_history: Mapped[Optional[str]] = mapped_column(Text)
    personal_history: Mapped[Optional[str]] = mapped_column(Text)
    physical_exam: Mapped[Optional[str]] = mapped_column(Text)
    initial_impression: Mapped[Optional[str]] = mapped_column(Text)
    # 住院部扩展字段
    marital_history: Mapped[Optional[str]] = mapped_column(Text)
    menstrual_history: Mapped[Optional[str]] = mapped_column(Text)
    family_history: Mapped[Optional[str]] = mapped_column(Text)
    history_informant: Mapped[Optional[str]] = mapped_column(Text)
    current_medications: Mapped[Optional[str]] = mapped_column(Text)
    rehabilitation_assessment: Mapped[Optional[str]] = mapped_column(Text)
    religion_belief: Mapped[Optional[str]] = mapped_column(Text)
    pain_assessment: Mapped[Optional[str]] = mapped_column(Text)
    vte_risk: Mapped[Optional[str]] = mapped_column(Text)
    nutrition_assessment: Mapped[Optional[str]] = mapped_column(Text)
    psychology_assessment: Mapped[Optional[str]] = mapped_column(Text)
    auxiliary_exam: Mapped[Optional[str]] = mapped_column(Text)
    admission_diagnosis: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)

    encounter: Mapped[Encounter] = relationship(back_populates="inquiry_inputs")


from app.models.patient import Patient
from app.models.medical_record import MedicalRecord
