from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from app.models.medical_record import MedicalRecord, RecordVersion
from app.schemas.medical_record import MedicalRecordCreate, RecordContentUpdate
from fastapi import HTTPException
from datetime import datetime


class MedicalRecordService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: MedicalRecordCreate) -> MedicalRecord:
        record = MedicalRecord(
            encounter_id=data.encounter_id,
            record_type=data.record_type,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_id(self, record_id: str, doctor_id: str | None = None) -> MedicalRecord:
        """获取病历。若传入 doctor_id 则同时校验归属权（接诊医生必须匹配）。"""
        from app.models.encounter import Encounter
        if doctor_id:
            result = await self.db.execute(
                select(MedicalRecord)
                .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
                .where(MedicalRecord.id == record_id, Encounter.doctor_id == doctor_id)
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=403, detail="病历不存在或无权访问")
            return record
        result = await self.db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id))
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="病历不存在")
        return record

    async def save_content(self, record_id: str, data: RecordContentUpdate, user_id: str):
        from app.models.encounter import Encounter
        result = await self.db.execute(
            select(MedicalRecord)
            .join(Encounter, Encounter.id == MedicalRecord.encounter_id)
            .where(MedicalRecord.id == record_id, Encounter.doctor_id == user_id)
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=403, detail="病历不存在或无权修改")
        if record.status == "submitted":
            raise HTTPException(status_code=403, detail="病历已签发，不可修改")
        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record_id,
            version_no=new_version_no,
            content=data.content,
            source="doctor_edited",
            triggered_by=user_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "editing"
        await self.db.commit()
        return {"ok": True, "version_no": new_version_no}

    async def quick_save(self, encounter_id: str, record_type: str, content: str, doctor_id: str) -> MedicalRecord:
        """签发时快速创建或更新病历记录"""
        # Check if a record already exists for this encounter+type (加锁防并发重复签发)
        result = await self.db.execute(
            select(MedicalRecord).where(
                MedicalRecord.encounter_id == encounter_id,
                MedicalRecord.record_type == record_type,
            ).with_for_update()
        )
        record = result.scalar_one_or_none()
        if not record:
            record = MedicalRecord(encounter_id=encounter_id, record_type=record_type)
            self.db.add(record)
            await self.db.flush()

        new_version_no = record.current_version + 1
        version = RecordVersion(
            medical_record_id=record.id,
            version_no=new_version_no,
            content={"text": content},
            source="doctor_signed",
            triggered_by=doctor_id,
        )
        self.db.add(version)
        record.current_version = new_version_no
        record.status = "submitted"
        record.submitted_at = datetime.now()
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def list_by_doctor(self, doctor_id: str, page: int = 1, page_size: int = 20) -> dict:
        """查询医生的历史签发病历"""
        from app.models.encounter import Encounter
        from app.models.patient import Patient
        from sqlalchemy import func

        offset = (page - 1) * page_size

        # Count
        count_q = (
            select(func.count())
            .select_from(MedicalRecord)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .where(Encounter.doctor_id == doctor_id, MedicalRecord.status == "submitted")
        )
        total = (await self.db.execute(count_q)).scalar() or 0

        # Records with encounter + patient
        q = (
            select(MedicalRecord, Encounter, Patient)
            .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
            .join(Patient, Encounter.patient_id == Patient.id)
            .where(Encounter.doctor_id == doctor_id, MedicalRecord.status == "submitted")
            .order_by(desc(MedicalRecord.submitted_at))
            .offset(offset)
            .limit(page_size)
        )
        rows = (await self.db.execute(q)).all()

        items = []
        for record, encounter, patient in rows:
            # Get latest version content
            ver_q = (
                select(RecordVersion)
                .where(RecordVersion.medical_record_id == record.id)
                .order_by(desc(RecordVersion.version_no))
                .limit(1)
            )
            ver = (await self.db.execute(ver_q)).scalar_one_or_none()
            content_text = ver.content.get("text", "") if ver and isinstance(ver.content, dict) else ""
            items.append({
                "id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "submitted_at": record.submitted_at,
                "patient_name": patient.name,
                "patient_gender": patient.gender,
                "encounter_id": encounter.id,
                "content_preview": content_text[:80] + "..." if len(content_text) > 80 else content_text,
                "content": content_text,
            })
        return {"total": total, "items": items}

    async def get_versions(self, record_id: str):
        result = await self.db.execute(
            select(RecordVersion)
            .where(RecordVersion.medical_record_id == record_id)
            .order_by(RecordVersion.version_no.desc())
        )
        versions = result.scalars().all()
        return {"items": [{"version_no": v.version_no, "source": v.source, "created_at": v.created_at} for v in versions]}
