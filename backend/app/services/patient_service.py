from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate
from fastapi import HTTPException
from datetime import date


class PatientService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find_existing(
        self,
        *,
        id_card: str | None = None,
        phone: str | None = None,
        name: str | None = None,
        birth_date: date | None = None,
    ) -> dict | None:
        patient = None

        if id_card:
            result = await self.db.execute(select(Patient).where(Patient.id_card == id_card))
            patient = result.scalar_one_or_none()

        if not patient and phone and name:
            result = await self.db.execute(
                select(Patient).where(Patient.phone == phone, Patient.name == name)
            )
            patient = result.scalar_one_or_none()

        if not patient and name and birth_date:
            result = await self.db.execute(
                select(Patient).where(Patient.name == name, Patient.birth_date == birth_date)
            )
            patient = result.scalar_one_or_none()

        return self._to_response(patient) if patient else None

    async def search(self, keyword: str, page: int, page_size: int):
        offset = (page - 1) * page_size
        query = select(Patient)
        if keyword:
            query = query.where(
                or_(Patient.name.ilike(f"%{keyword}%"), Patient.patient_no.ilike(f"%{keyword}%"))
            )
        count_result = await self.db.execute(select(func.count()).select_from(query.subquery()))
        total = count_result.scalar()
        result = await self.db.execute(query.offset(offset).limit(page_size))
        items = result.scalars().all()
        return {"total": total, "items": [self._to_response(p) for p in items]}

    async def create(self, data: PatientCreate) -> dict:
        patient = Patient(**data.model_dump(exclude_none=True))
        self.db.add(patient)
        await self.db.commit()
        await self.db.refresh(patient)
        return self._to_response(patient)

    async def update(self, patient_id: str, data: PatientUpdate) -> dict:
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(patient, field, value)
        await self.db.commit()
        await self.db.refresh(patient)
        return self._to_response(patient)

    async def get_by_id(self, patient_id: str) -> dict:
        result = await self.db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()
        if not patient:
            raise HTTPException(status_code=404, detail="患者不存在")
        return self._to_response(patient)

    def _to_response(self, patient: Patient) -> dict:
        age = None
        if patient.birth_date:
            today = date.today()
            age = today.year - patient.birth_date.year - (
                (today.month, today.day) < (patient.birth_date.month, patient.birth_date.day)
            )
        return {
            "id": patient.id,
            "patient_no": patient.patient_no,
            "name": patient.name,
            "gender": patient.gender,
            "age": age,
            "phone": patient.phone,
            "birth_date": patient.birth_date,
        }
