"""
病历路由（/api/v1/medical-records/*）

端点列表：
  POST   /quick-save              签发并快速保存病历
  GET    /my                      查询当前医生的历史签发病历
  POST   /                        标准创建病历记录
  GET    /{record_id}             查询单条病历
  POST   /{record_id}/generate    AI 生成病历（流式）
  POST   /{record_id}/continue    AI 续写病历（流式）
  POST   /{record_id}/polish      AI 润色病历（流式）
  PUT    /{record_id}/content     保存病历内容
  GET    /{record_id}/versions    获取历史版本列表
  POST   /{record_id}/qc/scan     触发 AI 质控扫描
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.core.authz import assert_patient_access
from app.database import get_db
from app.schemas.medical_record import (
    MedicalRecordCreate,
    MedicalRecordResponse,
    QuickSaveRequest,
    RecordContinueRequest,
    RecordContentUpdate,
    RecordGenerateRequest,
    RecordPolishRequest,
)
from app.services.ai.qc_service import QCService
from app.services.ai.record_gen_service import RecordGenService
from app.services.audit_service import log_action
from app.services.medical_record_service import MedicalRecordService

router = APIRouter()


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
    return {"ok": True, "record_id": record.id}


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


@router.get("/by-patient/{patient_id}")
async def list_by_patient(
    patient_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """查询某患者的全部已签发病历（门诊/急诊/住院）——住院医生查看患者来路用。

    权限：admin / radiologist 直通；其他角色必须对该患者有过接诊关系。
    返回字段包含 visit_type / is_first_visit 供前端打场景 Tag。
    """
    await assert_patient_access(db, patient_id, current_user)
    service = MedicalRecordService(db)
    return await service.list_by_patient(patient_id, page, page_size)


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
    return await service.get_by_id(record_id, doctor_id=current_user.id)


@router.post("/{record_id}/generate")
async def generate_record(
    record_id: str,
    request: RecordGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # stream_generate 内部已通过 get_by_id(doctor_id=user_id) 校验归属
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
    # stream_continue 不读取病历，先在此校验归属
    rec_service = MedicalRecordService(db)
    await rec_service.get_by_id(record_id, doctor_id=current_user.id)
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
    # stream_polish 不读取病历，先在此校验归属
    rec_service = MedicalRecordService(db)
    await rec_service.get_by_id(record_id, doctor_id=current_user.id)
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
    # 先校验归属权，再读版本列表
    await service.get_by_id(record_id, doctor_id=current_user.id)
    return await service.get_versions(record_id)


@router.post("/{record_id}/qc/scan")
async def scan_qc(
    record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 先校验归属权
    rec_service = MedicalRecordService(db)
    await rec_service.get_by_id(record_id, doctor_id=current_user.id)
    service = QCService(db)
    return await service.scan(record_id)
