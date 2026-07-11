"""
接诊问诊子路由（/api/v1/encounters/{id}/inquiry*, exam-suggestions, previous-record）

从 encounters.py 拆出（Round 5 瘦身）：负责问诊输入保存、上次病历同步，以及
问诊追问 / 辅助检查的 AI 建议。行为与拆分前逐字一致，路由路径/方法/依赖零改动。
本模块自建 router，由 encounters.py 主 router 拼回。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.authz import assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.ai_suggestion import InquirySuggestionRequest
from app.schemas.encounter import InquiryInputUpdate
from app.schemas.exam import ExamSuggestionRequest
from app.services.ai.exam_service import ExamService
from app.services.ai.inquiry_service import InquiryService
from app.services.encounter_service import EncounterService

router = APIRouter()


@router.put("/{encounter_id}/inquiry")
async def save_inquiry_input(
    encounter_id: str,
    data: InquiryInputUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存 / 更新问诊输入字段。"""
    # 归属校验：只能写自己接诊的问诊，防止越权覆写他人接诊数据
    await assert_encounter_access(db, encounter_id, current_user)
    service = EncounterService(db)
    return await service.save_inquiry(encounter_id, data)


@router.get("/{encounter_id}/previous-record")
async def get_previous_record(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """一键同步上次病历：返回该患者上次接诊的病历文字字段（体征不带回，需本次重测）。"""
    # 归属校验：只能对自己的接诊拉上次病历，防止越权拿他人患者的历史问诊全文
    await assert_encounter_access(db, encounter_id, current_user)
    service = EncounterService(db)
    return await service.get_previous_record(encounter_id)


@router.post("/{encounter_id}/inquiry-suggestions")
async def get_inquiry_suggestions(
    encounter_id: str,
    request: InquirySuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """生成问诊追问建议（流式）。"""
    # 归属校验：只能对自己的接诊生成建议（流开始前先挡住越权）
    await assert_encounter_access(db, encounter_id, current_user)
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
    """生成辅助检查建议。"""
    # 归属校验：只能对自己的接诊生成建议
    await assert_encounter_access(db, encounter_id, current_user)
    service = ExamService(db)
    return await service.get_suggestions(encounter_id, request)
