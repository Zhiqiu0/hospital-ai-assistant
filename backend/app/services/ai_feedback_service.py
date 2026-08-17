"""
AI 建议反馈服务（app/services/ai_feedback_service.py）

2026-06-11 Round 5 迁移：业务逻辑从 app/api/v1/ai_feedback.py 下沉到 service 层，
路由层只保留请求解析 + 鉴权 + 调 service，行为零改变。

职责：
  - submit_feedback : 校验并写入一条医生对 AI 建议的点赞/点踩反馈，
                      自动打上 (prompt_version, prompt_scene, model_name) 标签

地基设计：写入反馈时自动打上 (prompt_version, prompt_scene, model_name) 标签，
future 档次 2（把负例塞回 prompt）必须按版本分层才能避免污染新 prompt。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.ai_feedback import AISuggestionFeedback
from app.services.ai.llm_client import llm_client

logger = logging.getLogger(__name__)


# 反馈 category → 提示词 scene 名（与 ai_suggestions 路由的场景标识一致）
# 当前只有 inquiry / exam 两种对应的提示词；diagnosis 暂无对应，留空
_CATEGORY_TO_PROMPT_SCENE: dict[str, Optional[str]] = {
    "inquiry": "inquiry",
    "exam": "exam",
    "diagnosis": None,
}

# 提示词版本标签：提示词全部代码内置（2026-08-18 撤掉 DB 自定义模板后唯一来源），
# 沿用历史数据里的 'hardcoded' 标签，保证新旧反馈可以按同一口径分层。
_CODE_PROMPT_VERSION = "hardcoded"


class AIFeedbackService:
    """AI 建议反馈数据访问服务，封装反馈写入与版本标签解析逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def submit_feedback(self, data, current_user) -> dict:
        """记录一条医生对 AI 建议的反馈，自动打上当前 prompt 版本和模型名标签。

        Args:
            data: FeedbackIn 请求体（encounter_id / suggestion_category /
                  suggestion_id / suggestion_text / verdict / comment）。
            current_user: 当前登录医生（取 id 写入 doctor_id，username 用于日志）。

        Raises:
            HTTPException(400): verdict 或 suggestion_category 取值非法。

        Returns:
            {"ok": True, "id": 新反馈记录 ID}
        """
        if data.verdict not in ("useful", "useless"):
            raise HTTPException(status_code=400, detail="verdict 必须是 useful 或 useless")
        if data.suggestion_category not in ("inquiry", "exam", "diagnosis"):
            raise HTTPException(status_code=400, detail="suggestion_category 必须是 inquiry/exam/diagnosis")

        # 打上生成链路标签：提示词版本（代码内置 → 'hardcoded'；diagnosis 无对应
        # 提示词 scene → None）与实际模型名（全局默认模型，与 get_model_options 同源）
        prompt_scene = _CATEGORY_TO_PROMPT_SCENE.get(data.suggestion_category)
        prompt_version = _CODE_PROMPT_VERSION if prompt_scene else None
        model_name = llm_client.model

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
        self.db.add(fb)
        await self.db.commit()
        await self.db.refresh(fb)
        logger.info(
            "AI feedback recorded: %s/%s by %s (prompt=%s@%s model=%s)",
            data.suggestion_category, data.verdict, current_user.username,
            prompt_scene or "-", prompt_version or "-", model_name or "-",
        )
        return {"ok": True, "id": fb.id}
