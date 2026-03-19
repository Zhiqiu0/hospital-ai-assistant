from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict
from typing import Optional
from app.database import get_db
from app.core.security import require_admin
from app.models.config import ModelConfig

router = APIRouter()

SCENE_DEFAULTS = [
    {"scene": "generate", "description": "病历生成（AI 起草病历）"},
    {"scene": "polish", "description": "病历润色（AI 优化措辞）"},
    {"scene": "qc", "description": "质控分析（AI 检查病历质量）"},
    {"scene": "inquiry", "description": "问诊建议（AI 补充追问要点）"},
    {"scene": "exam", "description": "检查推荐（AI 推荐辅助检查）"},
]


class ModelConfigUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    temperature: float
    max_tokens: int
    is_active: bool
    description: Optional[str] = None


async def _ensure_defaults(db: AsyncSession):
    """Seed default rows for all scenes if they don't exist yet."""
    for item in SCENE_DEFAULTS:
        result = await db.execute(
            select(ModelConfig).where(ModelConfig.scene == item["scene"])
        )
        if not result.scalar_one_or_none():
            db.add(ModelConfig(
                scene=item["scene"],
                model_name="deepseek-chat",
                temperature=0.3,
                max_tokens=4096,
                is_active=True,
                description=item["description"],
            ))
    await db.commit()


@router.get("")
async def list_model_configs(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    await _ensure_defaults(db)
    result = await db.execute(select(ModelConfig).order_by(ModelConfig.scene))
    configs = result.scalars().all()
    return [
        {
            "id": c.id,
            "scene": c.scene,
            "model_name": c.model_name,
            "temperature": c.temperature,
            "max_tokens": c.max_tokens,
            "is_active": c.is_active,
            "description": c.description,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in configs
    ]


@router.put("/{scene}")
async def update_model_config(
    scene: str,
    data: ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    await _ensure_defaults(db)
    result = await db.execute(select(ModelConfig).where(ModelConfig.scene == scene))
    config = result.scalar_one_or_none()
    if not config:
        config = ModelConfig(scene=scene)
        db.add(config)
    config.model_name = data.model_name
    config.temperature = data.temperature
    config.max_tokens = data.max_tokens
    config.is_active = data.is_active
    if data.description is not None:
        config.description = data.description
    await db.commit()
    await db.refresh(config)
    return {"message": "保存成功", "scene": config.scene}
