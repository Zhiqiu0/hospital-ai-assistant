"""
模型配置读取工具（app/services/ai/model_options.py）

提供 ``get_model_options`` 从数据库读取指定场景的 LLM 配置，
供所有 AI 路由及服务统一调用，避免分散重复。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.config import ModelConfig
from app.services.ai.llm_client import llm_client


async def get_model_options(db: AsyncSession, scene: str) -> dict:
    """从 DB 读取指定场景的模型配置，找不到时返回全局默认值。

    Args:
        db: 异步数据库会话。
        scene: 场景标识（如 'generate'、'qc'、'inquiry'、'exam'、'polish'）。

    Returns:
        包含 model_name / temperature / max_tokens 的配置字典。
    """
    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.scene == scene,
            ModelConfig.is_active == True,
        ).limit(1)
    )
    config = result.scalar_one_or_none()
    return {
        "model_name": config.model_name if config else llm_client.model,
        "temperature": config.temperature if config else 0.3,
        "max_tokens": config.max_tokens if config else 4096,
    }
