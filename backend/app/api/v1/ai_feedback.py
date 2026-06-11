"""
AI 建议反馈路由（/api/v1/ai/suggestion-feedback）

医生对 AI 追问/检查/诊断建议点赞点踩的数据收集端点。
只写不读（读留给运营后台），所以只暴露 POST。

业务逻辑已下沉到 app/services/ai_feedback_service.py（2026-06-11 Round 5 迁移），
本文件只保留请求解析 + 鉴权 + 调 service。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import get_current_user
from app.services.ai_feedback_service import AIFeedbackService

router = APIRouter()


class FeedbackIn(BaseModel):
    """AI 建议反馈请求体。"""

    encounter_id: Optional[str] = None
    suggestion_category: str              # inquiry / exam / diagnosis
    suggestion_id: Optional[str] = None
    suggestion_text: str
    verdict: str                          # useful / useless
    comment: Optional[str] = None


@router.post("/suggestion-feedback", status_code=201)
async def submit_feedback(
    data: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """记录一条医生对 AI 建议的反馈，自动打上当前 prompt 版本和模型名标签。"""
    service = AIFeedbackService(db)
    return await service.submit_feedback(data, current_user)
