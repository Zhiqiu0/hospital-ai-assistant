"""最终正文诊断核对预览接口；确认结果由签发/修订请求重新验证后保存。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.schemas.diagnosis_confirmation import DiagnosisPreviewRequest, DiagnosisPreviewResponse
from app.services.record_diagnosis_preview import preview_record_diagnoses

router = APIRouter()


@router.post("/diagnosis-preview", response_model=DiagnosisPreviewResponse)
async def diagnosis_preview(request: DiagnosisPreviewRequest, db: AsyncSession = Depends(get_db),
                            current_user=Depends(get_current_user)):
    """按最终正文提供完整诊断列表，供用户明确核对主诊断；不会改问诊或历史版本。"""
    return await preview_record_diagnoses(db, request, current_user)
