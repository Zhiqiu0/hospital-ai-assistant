from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.config import ModelConfig
from app.services.ai.llm_client import llm_client


async def get_model_options(db: AsyncSession, scene: str) -> dict:
    """从 DB 读取指定场景的模型配置，找不到时返回全局默认值。"""
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
