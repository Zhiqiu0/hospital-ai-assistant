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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.ai_feedback import AISuggestionFeedback
from app.models.config import ModelConfig, PromptTemplate

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


class AIFeedbackService:
    """AI 建议反馈数据访问服务，封装反馈写入与版本标签解析逻辑。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_prompt_version(self, scene: Optional[str]) -> Optional[str]:
        """取指定 scene 的当前激活 prompt 模板版本号。

        若 DB 里无该 scene 的 active 模板（说明此刻用的是代码硬编码 prompt），
        回退标签 'hardcoded'，让未来能清晰区分"代码 prompt 时期 vs 可配置时期"的反馈，
        避免混用数据做优化。scene 为空（如 diagnosis 类别）才返 None。
        """
        if not scene:
            return None
        result = await self.db.execute(
            select(PromptTemplate.version)
            .where(PromptTemplate.scene == scene, PromptTemplate.is_active.is_(True))
            .order_by(PromptTemplate.created_at.desc())
            .limit(1)
        )
        version = result.scalar_one_or_none()
        return version or "hardcoded"

    async def _resolve_model_name(self, scene: Optional[str]) -> Optional[str]:
        """取指定 scene 的当前激活 model_name。

        若 DB 无该 scene 的 ModelConfig，回退到 settings.deepseek_model（工作台默认模型）。
        这样反馈永远能标注"这条建议是哪个模型吐出来的"，未来换模型时数据能干净分层。
        """
        if scene:
            result = await self.db.execute(
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

        # 解析当前生成链路的 prompt 版本和模型名（查不到存 None 不阻塞反馈写入）
        prompt_scene = _CATEGORY_TO_PROMPT_SCENE.get(data.suggestion_category)
        model_scene = _CATEGORY_TO_MODEL_SCENE.get(data.suggestion_category)
        prompt_version = await self._resolve_prompt_version(prompt_scene)
        model_name = await self._resolve_model_name(model_scene)

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
