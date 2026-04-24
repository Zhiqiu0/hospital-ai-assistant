"""
AI 建议反馈路由（/api/v1/ai/suggestion-feedback）

医生对 AI 追问/检查/诊断建议点赞点踩的数据收集端点。
只写不读（读留给运营后台），所以只暴露 POST。

地基设计：写入反馈时自动打上 (prompt_version, prompt_scene, model_name) 标签，
future 档次 2（把负例塞回 prompt）必须按版本分层才能避免污染新 prompt。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import get_current_user
from app.models.ai_feedback import AISuggestionFeedback
from app.models.config import ModelConfig, PromptTemplate

router = APIRouter()
logger = logging.getLogger(__name__)


# 反馈 category → prompt 模板的 scene 名（PromptTemplate.scene 字段）
# 当前只有 inquiry / exam 两种对应的 prompt 模板；diagnosis 暂无对应模板，留空
_CATEGORY_TO_PROMPT_SCENE: dict[str, Optional[str]] = {
    "inquiry": "inquiry",
    "exam": "exam",
    "diagnosis": None,
}

# 反馈 category → 生成模型配置 scene（ModelConfig.scene 字段）
# 所有建议类 AI 任务共用 "suggestions" 模型配置（如存在），否则回退到 None
_CATEGORY_TO_MODEL_SCENE: dict[str, Optional[str]] = {
    "inquiry": "suggestions",
    "exam": "suggestions",
    "diagnosis": "suggestions",
}


async def _resolve_prompt_version(db: AsyncSession, scene: Optional[str]) -> Optional[str]:
    """取指定 scene 的当前激活 prompt 模板版本号。

    若 DB 里无该 scene 的 active 模板（说明此刻用的是代码硬编码 prompt），
    回退标签 'hardcoded'，让未来能清晰区分"代码 prompt 时期 vs 可配置时期"的反馈，
    避免混用数据做优化。scene 为空（如 diagnosis 类别）才返 None。
    """
    if not scene:
        return None
    result = await db.execute(
        select(PromptTemplate.version)
        .where(PromptTemplate.scene == scene, PromptTemplate.is_active.is_(True))
        .order_by(PromptTemplate.created_at.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    return version or "hardcoded"


async def _resolve_model_name(db: AsyncSession, scene: Optional[str]) -> Optional[str]:
    """取指定 scene 的当前激活 model_name。

    若 DB 无该 scene 的 ModelConfig，回退到 settings.deepseek_model（工作台默认模型）。
    这样反馈永远能标注"这条建议是哪个模型吐出来的"，未来换模型时数据能干净分层。
    """
    if scene:
        result = await db.execute(
            select(ModelConfig.model_name)
            .where(ModelConfig.scene == scene, ModelConfig.is_active.is_(True))
            .limit(1)
        )
        name = result.scalar_one_or_none()
        if name:
            return name
    # 回退到全局默认模型配置
    from app.config import settings
    return settings.deepseek_model


class FeedbackIn(BaseModel):
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
    if data.verdict not in ("useful", "useless"):
        raise HTTPException(status_code=400, detail="verdict 必须是 useful 或 useless")
    if data.suggestion_category not in ("inquiry", "exam", "diagnosis"):
        raise HTTPException(status_code=400, detail="suggestion_category 必须是 inquiry/exam/diagnosis")

    # 解析当前生成链路的 prompt 版本和模型名（查不到存 None 不阻塞反馈写入）
    prompt_scene = _CATEGORY_TO_PROMPT_SCENE.get(data.suggestion_category)
    model_scene = _CATEGORY_TO_MODEL_SCENE.get(data.suggestion_category)
    prompt_version = await _resolve_prompt_version(db, prompt_scene)
    model_name = await _resolve_model_name(db, model_scene)

    fb = AISuggestionFeedback(
        encounter_id=data.encounter_id,
        doctor_id=str(getattr(current_user, "id", None) or ""),
        suggestion_category=data.suggestion_category,
        suggestion_id=data.suggestion_id,
        suggestion_text=data.suggestion_text,
        verdict=data.verdict,
        comment=data.comment,
        prompt_version=prompt_version,
        prompt_scene=prompt_scene,
        model_name=model_name,
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    logger.info(
        "AI feedback recorded: %s/%s by %s (prompt=%s@%s model=%s)",
        data.suggestion_category, data.verdict, current_user.username,
        prompt_scene or "-", prompt_version or "-", model_name or "-",
    )
    return {"ok": True, "id": fb.id}
