"""
模型配置读取工具（app/services/ai/model_options.py）

提供 ``get_model_options`` 从数据库读取指定场景的 LLM 配置，
供所有 AI 路由及服务统一调用，避免分散重复。

缓存策略：
  - 配置型数据，admin 改才会变；每次 AI 调用前都查 DB 是浪费
  - Redis 缓存 60 秒；admin 写 ModelConfig 时主动调
    invalidate_model_options(scene) 失效
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.config import ModelConfig
from app.services.ai.llm_client import llm_client
from app.services.redis_cache import redis_cache

# 模型配置 Redis key 前缀。失效时按 scene 精确删除，避免连带删
_CACHE_KEY = "ai:model_options:{scene}"
_CACHE_TTL = 60  # 1 分钟，admin 改后最多 60s 后所有进程生效


async def get_model_options(db: AsyncSession, scene: str) -> dict:
    """从 DB 读取指定场景的模型配置，找不到时返回全局默认值。

    Args:
        db: 异步数据库会话。
        scene: 场景标识（如 'generate'、'qc'、'inquiry'、'exam'、'polish'）。

    Returns:
        包含 model_name / temperature / max_tokens 的配置字典。
    """
    cache_key = _CACHE_KEY.format(scene=scene)
    cached = await redis_cache.get_json(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(ModelConfig).where(
            ModelConfig.scene == scene,
            ModelConfig.is_active.is_(True),
        ).limit(1)
    )
    config = result.scalar_one_or_none()
    options = {
        "model_name": config.model_name if config else llm_client.model,
        "temperature": config.temperature if config else 0.3,
        "max_tokens": config.max_tokens if config else 4096,
    }
    await redis_cache.set_json(cache_key, options, ttl=_CACHE_TTL)
    return options


async def invalidate_model_options(scene: str | None = None) -> None:
    """admin 写 ModelConfig 后调，失效缓存让所有进程立即看到新配置。

    Args:
        scene: 指定 scene 失效；传 None 失效全部场景（删整个前缀）。
    """
    if scene:
        await redis_cache.delete(_CACHE_KEY.format(scene=scene))
    else:
        await redis_cache.delete_prefix("ai:model_options:")
