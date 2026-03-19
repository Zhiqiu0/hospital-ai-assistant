from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.schemas.medical_record import (
    MedicalRecordCreate, MedicalRecordResponse,
    RecordContentUpdate, RecordGenerateRequest,
    RecordContinueRequest, RecordPolishRequest,
)
from app.services.medical_record_service import MedicalRecordService
from app.services.ai.record_gen_service import RecordGenService
from app.core.security import get_current_user
from app.services.audit_service import log_action

router = APIRouter()


class QuickSaveRequest(BaseModel):
    encounter_id: str
    record_type: str = "outpatient"
    content: str


@router.post("/quick-save")
async def quick_save_record(
    data: QuickSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """签发时快速保存病历到数据库"""
    service = MedicalRecordService(db)
    record = await service.quick_save(
        encounter_id=data.encounter_id,
        record_type=data.record_type,
        content=data.content,
        doctor_id=current_user.id,
    )
    await log_action(
        action="sign_record",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="medical_record",
        resource_id=record.id,
        detail=f"签发病历，类型：{data.record_type}，接诊ID：{data.encounter_id}",
    )
    return {"record_id": record.id, "message": "病历已保存"}


@router.get("/my")
async def list_my_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查询当前医生的历史签发病历"""
    service = MedicalRecordService(db)
    return await service.list_by_doctor(current_user.id, page, page_size)


@router.post("", response_model=MedicalRecordResponse, status_code=201)
async def create_record(
    data: MedicalRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    return await service.create(data)


@router.get("/{record_id}", response_model=MedicalRecordResponse)
async def get_record(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    return await service.get_by_id(record_id)


@router.post("/{record_id}/generate")
async def generate_record(
    record_id: str,
    request: RecordGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = RecordGenService(db)
    return StreamingResponse(
        service.stream_generate(record_id, request, current_user.id),
        media_type="text/event-stream",
    )


@router.post("/{record_id}/continue")
async def continue_record(
    record_id: str,
    request: RecordContinueRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = RecordGenService(db)
    return StreamingResponse(
        service.stream_continue(record_id, request, current_user.id),
        media_type="text/event-stream",
    )


@router.post("/{record_id}/polish")
async def polish_record(
    record_id: str,
    request: RecordPolishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = RecordGenService(db)
    return StreamingResponse(
        service.stream_polish(record_id, request, current_user.id),
        media_type="text/event-stream",
    )


@router.put("/{record_id}/content")
async def save_record_content(
    record_id: str,
    data: RecordContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    return await service.save_content(record_id, data, current_user.id)


@router.get("/{record_id}/versions")
async def get_record_versions(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = MedicalRecordService(db)
    return await service.get_versions(record_id)


@router.post("/{record_id}/qc/scan")
async def scan_qc(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from app.services.ai.qc_service import QCService
    service = QCService(db)
    return await service.scan(record_id)
