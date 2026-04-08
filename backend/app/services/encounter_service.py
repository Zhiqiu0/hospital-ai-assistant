from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.voice_record import VoiceRecord
from app.schemas.encounter import EncounterCreate, InquiryInputUpdate
from fastapi import HTTPException


class EncounterService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: EncounterCreate, doctor_id: str) -> Encounter:
        encounter = Encounter(
            patient_id=data.patient_id,
            doctor_id=doctor_id,
            department_id=data.department_id,
            visit_type=data.visit_type,
            is_first_visit=data.is_first_visit,
            bed_no=data.bed_no,
            admission_route=data.admission_route,
            admission_condition=data.admission_condition,
        )
        self.db.add(encounter)
        await self.db.commit()
        await self.db.refresh(encounter)
        return encounter

    async def get_my_encounters(self, doctor_id: str, limit: int = 20):
        result = await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))
            .where(Encounter.doctor_id == doctor_id, Encounter.status == "in_progress")
            .order_by(Encounter.visited_at.desc())
            .limit(limit)
        )
        encounters = result.scalars().all()
        return [
            {
                "encounter_id": e.id,
                "visit_type": e.visit_type,
                "status": e.status,
                "visited_at": e.visited_at.isoformat() if e.visited_at else None,
                "chief_complaint_brief": e.chief_complaint_brief,
                "patient": {
                    "id": e.patient.id,
                    "name": e.patient.name,
                    "gender": e.patient.gender,
                    "age": (
                        (
                            __import__("datetime").date.today().year
                            - e.patient.birth_date.year
                        )
                        if e.patient.birth_date
                        else None
                    ),
                } if e.patient else None,
            }
            for e in encounters
        ]

    async def get_by_id(self, encounter_id: str) -> Encounter:
        result = await self.db.execute(select(Encounter).where(Encounter.id == encounter_id))
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="就诊记录不存在")
        return encounter

    async def get_workspace_snapshot(self, encounter_id: str, doctor_id: str) -> dict:
        encounter_result = await self.db.execute(
            select(Encounter)
            .options(selectinload(Encounter.patient))
            .where(Encounter.id == encounter_id, Encounter.doctor_id == doctor_id)
        )
        encounter = encounter_result.scalar_one_or_none()
        if not encounter:
            raise HTTPException(status_code=404, detail="接诊记录不存在或无权访问")

        inquiry_result = await self.db.execute(
            select(InquiryInput)
            .where(InquiryInput.encounter_id == encounter_id)
            .order_by(desc(InquiryInput.updated_at))
            .limit(1)
        )
        inquiry = inquiry_result.scalar_one_or_none()

        records_result = await self.db.execute(
            select(MedicalRecord)
            .where(MedicalRecord.encounter_id == encounter_id)
            .order_by(desc(MedicalRecord.updated_at), desc(MedicalRecord.submitted_at))
        )
        records = records_result.scalars().all()

        record_items = []
        for record in records:
            version_result = await self.db.execute(
                select(RecordVersion)
                .where(
                    RecordVersion.medical_record_id == record.id,
                    RecordVersion.version_no == record.current_version,
                )
                .limit(1)
            )
            version = version_result.scalar_one_or_none()
            content = version.content if version else None
            if isinstance(content, dict):
                content_text = content.get("text", "")
            elif isinstance(content, str):
                content_text = content
            else:
                content_text = ""

            record_items.append({
                "record_id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "current_version": record.current_version,
                "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
                "updated_at": record.updated_at.isoformat() if record.updated_at else None,
                "content": content_text,
            })

        active_record = record_items[0] if record_items else None
        voice_result = await self.db.execute(
            select(VoiceRecord)
            .where(VoiceRecord.encounter_id == encounter_id)
            .order_by(desc(VoiceRecord.updated_at), desc(VoiceRecord.created_at))
            .limit(1)
        )
        latest_voice = voice_result.scalar_one_or_none()
        patient = encounter.patient
        patient_age = None
        if patient and patient.birth_date:
            today = __import__("datetime").date.today()
            patient_age = today.year - patient.birth_date.year - (
                (today.month, today.day) < (patient.birth_date.month, patient.birth_date.day)
            )

        return {
            "encounter_id": encounter.id,
            "visit_type": encounter.visit_type,
            "status": encounter.status,
            "patient": {
                "id": patient.id,
                "name": patient.name,
                "gender": patient.gender,
                "age": patient_age,
            } if patient else None,
            "inquiry": {
                "chief_complaint": inquiry.chief_complaint or "",
                "history_present_illness": inquiry.history_present_illness or "",
                "past_history": inquiry.past_history or "",
                "allergy_history": inquiry.allergy_history or "",
                "personal_history": inquiry.personal_history or "",
                "physical_exam": inquiry.physical_exam or "",
                "initial_impression": inquiry.initial_impression or "",
                "marital_history": inquiry.marital_history or "",
                "menstrual_history": inquiry.menstrual_history or "",
                "family_history": inquiry.family_history or "",
                "history_informant": inquiry.history_informant or "",
                "current_medications": inquiry.current_medications or "",
                "rehabilitation_assessment": inquiry.rehabilitation_assessment or "",
                "religion_belief": inquiry.religion_belief or "",
                "pain_assessment": inquiry.pain_assessment or "",
                "vte_risk": inquiry.vte_risk or "",
                "nutrition_assessment": inquiry.nutrition_assessment or "",
                "psychology_assessment": inquiry.psychology_assessment or "",
                "auxiliary_exam": inquiry.auxiliary_exam or "",
                "admission_diagnosis": inquiry.admission_diagnosis or "",
                "tcm_inspection": inquiry.tcm_inspection or "",
                "tcm_auscultation": inquiry.tcm_auscultation or "",
                "tongue_coating": inquiry.tongue_coating or "",
                "pulse_condition": inquiry.pulse_condition or "",
                "western_diagnosis": inquiry.western_diagnosis or "",
                "tcm_disease_diagnosis": inquiry.tcm_disease_diagnosis or "",
                "tcm_syndrome_diagnosis": inquiry.tcm_syndrome_diagnosis or "",
                "treatment_method": inquiry.treatment_method or "",
                "treatment_plan": inquiry.treatment_plan or "",
                "followup_advice": inquiry.followup_advice or "",
                "precautions": inquiry.precautions or "",
                "observation_notes": inquiry.observation_notes or "",
                "patient_disposition": inquiry.patient_disposition or "",
                # 就诊时间：有记录用记录，否则从 encounter.visited_at 预填
                "visit_time": inquiry.visit_time or (
                    encounter.visited_at.strftime("%Y-%m-%d %H:%M") if encounter.visited_at else ""
                ),
                "onset_time": inquiry.onset_time or "",
                "version": inquiry.version,
            } if inquiry else None,
            "is_first_visit": encounter.is_first_visit,
            "active_record": active_record,
            "records": record_items,
            "latest_voice_record": {
                "id": latest_voice.id,
                "status": latest_voice.status,
                "raw_transcript": latest_voice.raw_transcript or "",
                "transcript_summary": latest_voice.transcript_summary or "",
                "speaker_dialogue": latest_voice.get_speaker_dialogue(),
                "draft_record": latest_voice.draft_record or "",
            } if latest_voice else None,
        }

    async def save_inquiry(self, encounter_id: str, data: InquiryInputUpdate):
        result = await self.db.execute(
            select(InquiryInput).where(InquiryInput.encounter_id == encounter_id)
        )
        inquiry = result.scalar_one_or_none()
        if inquiry:
            for field, value in data.model_dump(exclude_none=True).items():
                setattr(inquiry, field, value)
            inquiry.version += 1
        else:
            inquiry = InquiryInput(encounter_id=encounter_id, **data.model_dump(exclude_none=True))
            self.db.add(inquiry)
        await self.db.commit()
        await self.db.refresh(inquiry)
        return {
            "message": "保存成功",
            "version": inquiry.version,
            "chief_complaint": inquiry.chief_complaint,
            "history_present_illness": inquiry.history_present_illness,
        }
