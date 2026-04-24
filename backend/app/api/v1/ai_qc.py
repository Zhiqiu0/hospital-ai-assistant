"""
AI 质控路由（/api/v1/ai/quick-qc 等）

端点列表：
  POST   /quick-qc       规则引擎 + LLM 双重质控，SSE 流式返回
  POST   /qc-fix         针对单条质控问题生成修复文本
  POST   /grade-score    甲级病历评分

业务逻辑全部在 app.services.ai.qc_stream_service；本文件只做 SSE 包装、鉴权、审计。
"""

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.schemas.ai_request import GradeScoreRequest, QCFixRequest, QuickQCRequest
from app.services.ai import qc_stream_service
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/quick-qc")
async def quick_qc(
    req: QuickQCRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """SSE 流式质控：规则引擎结果立即推送，LLM 质量建议追加推送。"""
    await log_action(
        action="ai_quick_qc",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'}",
    )

    async def sse_wrap():
        async for event in qc_stream_service.run_quick_qc_stream(db, req):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        sse_wrap(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/qc-fix")
async def qc_fix(
    req: QCFixRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """单条质控问题的修复文本生成。"""
    await log_action(
        action="ai_qc_fix",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"field={req.field_name or 'unknown'}",
    )
    fix_text = await qc_stream_service.run_qc_fix(db, req)
    return {"fix_text": fix_text}


@router.post("/grade-score")
async def grade_score(
    req: GradeScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """甲级病历评分（0-100）。"""
    return await qc_stream_service.run_grade_score(db, req)
