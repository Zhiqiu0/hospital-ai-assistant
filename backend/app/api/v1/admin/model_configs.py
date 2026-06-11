"""
管理后台模型配置接口（/api/v1/admin/model-configs/*）

允许管理员按场景（generate / polish / qc / inquiry / exam）
配置 LLM 模型名称、温度、最大 token 等参数。

业务逻辑已下沉到 app/services/prompt_template_service.py 的 ModelConfigService
（2026-06-11 Round 5 迁移，与 Prompt 模板同属 LLM 配置域），
本文件只保留请求解析 + 鉴权 + 调 service。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import require_admin
from app.database import get_db
from app.services.prompt_template_service import ModelConfigService

router = APIRouter()


class ModelConfigUpdate(BaseModel):
    """模型配置更新请求体（model_name 与 pydantic 保护前缀冲突，需关闭保护）。"""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    temperature: float
    max_tokens: int
    is_active: bool
    description: Optional[str] = None


@router.get("")
async def list_model_configs(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """列出全部场景的模型配置（首次访问自动 seed 默认行）。"""
    service = ModelConfigService(db)
    return await service.list_configs()


@router.put("/{scene}")
async def update_model_config(
    scene: str,
    data: ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """更新指定 scene 的模型配置（写库后自动失效该 scene 的模型配置缓存）。"""
    service = ModelConfigService(db)
    return await service.update(
        scene,
        model_name=data.model_name,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        is_active=data.is_active,
        description=data.description,
    )
