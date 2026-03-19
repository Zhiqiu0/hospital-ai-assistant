from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.schemas.encounter import EncounterCreate, EncounterResponse, InquiryInputUpdate
from app.schemas.ai_suggestion import InquirySuggestionRequest
from app.schemas.exam import ExamSuggestionRequest
from app.services.encounter_service import EncounterService
from app.services.patient_service import PatientService
from app.services.ai.inquiry_service import InquiryService
from app.services.ai.exam_service import ExamService
from app.core.security import get_current_user

router = APIRouter()


class QuickStartRequest(BaseModel):
    """一键开始接诊：自动创建患者（如有需要）并创建接诊记录"""
    patient_name: str
    gender: Optional[str] = "unknown"
    age: Optional[int] = None
    birth_date: Optional[str] = None          # YYYY-MM-DD
    id_card: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    ethnicity: Optional[str] = None
    marital_status: Optional[str] = None
    occupation: Optional[str] = None
    workplace: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    blood_type: Optional[str] = None
    visit_type: str = "outpatient"
    department_id: Optional[str] = None
    bed_no: Optional[str] = None
    admission_route: Optional[str] = None
    admission_condition: Optional[str] = None


@router.post("/quick-start")
async def quick_start_encounter(
    data: QuickStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """快速开始接诊：创建患者 + 接诊记录，返回 encounter_id 和 patient 信息"""
    from app.schemas.patient import PatientCreate
    from datetime import date
    # 解析出生日期：优先使用 birth_date 字符串，其次从 age 推算
    birth_date_val = None
    if data.birth_date:
        try:
            birth_date_val = date.fromisoformat(data.birth_date)
        except ValueError:
            pass
    elif data.age:
        birth_date_val = date(date.today().year - data.age, 1, 1)

    patient_service = PatientService(db)
    patient = await patient_service.find_existing(
        id_card=data.id_card,
        phone=data.phone,
        name=data.patient_name,
        birth_date=birth_date_val,
    )
    patient_reused = patient is not None
    if not patient:
        patient = await patient_service.create(PatientCreate(
            name=data.patient_name,
            gender=data.gender,
            birth_date=birth_date_val,
            id_card=data.id_card,
            phone=data.phone,
            address=data.address,
            ethnicity=data.ethnicity,
            marital_status=data.marital_status,
            occupation=data.occupation,
            workplace=data.workplace,
            contact_name=data.contact_name,
            contact_phone=data.contact_phone,
            contact_relation=data.contact_relation,
            blood_type=data.blood_type,
        ))
    encounter_service = EncounterService(db)
    encounter = await encounter_service.create(
        EncounterCreate(
            patient_id=patient["id"],
            visit_type=data.visit_type,
            department_id=data.department_id or current_user.department_id,
            is_first_visit=True,
            bed_no=data.bed_no,
            admission_route=data.admission_route,
            admission_condition=data.admission_condition,
        ),
        current_user.id,
    )
    return {
        "encounter_id": encounter.id,
        "patient": patient,
        "visit_type": data.visit_type,
        "patient_reused": patient_reused,
    }


@router.post("", response_model=EncounterResponse, status_code=201)
async def create_encounter(
    data: EncounterCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = EncounterService(db)
    return await service.create(data, current_user.id)


@router.get("/my")
async def get_my_encounters(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取当前医生的进行中接诊列表"""
    service = EncounterService(db)
    return await service.get_my_encounters(current_user.id)


@router.get("/{encounter_id}", response_model=EncounterResponse)
async def get_encounter(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = EncounterService(db)
    return await service.get_by_id(encounter_id)


@router.get("/{encounter_id}/workspace")
async def get_encounter_workspace(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """恢复工作台所需数据：患者、问诊、最近病历草稿/已签发内容。"""
    service = EncounterService(db)
    return await service.get_workspace_snapshot(encounter_id, current_user.id)


@router.put("/{encounter_id}/inquiry")
async def save_inquiry_input(
    encounter_id: str,
    data: InquiryInputUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = EncounterService(db)
    return await service.save_inquiry(encounter_id, data)


@router.post("/{encounter_id}/inquiry-suggestions")
async def get_inquiry_suggestions(
    encounter_id: str,
    request: InquirySuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = InquiryService(db)
    return StreamingResponse(
        service.stream_suggestions(encounter_id, request),
        media_type="text/event-stream",
    )


@router.post("/{encounter_id}/exam-suggestions")
async def get_exam_suggestions(
    encounter_id: str,
    request: ExamSuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = ExamService(db)
    return await service.get_suggestions(encounter_id, request)
