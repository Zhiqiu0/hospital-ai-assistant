from pydantic import BaseModel
from typing import Optional
import datetime


class PatientCreate(BaseModel):
    name: str
    gender: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    phone: Optional[str] = None
    id_card: Optional[str] = None
    address: Optional[str] = None
    ethnicity: Optional[str] = None
    marital_status: Optional[str] = None
    occupation: Optional[str] = None
    workplace: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    blood_type: Optional[str] = None


class PatientResponse(BaseModel):
    id: str
    patient_no: Optional[str] = None
    name: str
    gender: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None

    class Config:
        from_attributes = True


class PatientUpdate(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    phone: Optional[str] = None
    id_card: Optional[str] = None
    address: Optional[str] = None
    ethnicity: Optional[str] = None
    marital_status: Optional[str] = None
    occupation: Optional[str] = None
    workplace: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    blood_type: Optional[str] = None


class PatientListResponse(BaseModel):
    total: int
    items: list[PatientResponse]
