"""
管理后台 Prompt 模板接口（/api/v1/admin/prompts/*）

支持按场景（scene）管理 LLM prompt 模板，激活的模板将覆盖代码内置默认值。

业务逻辑已下沉到 app/services/prompt_template_service.py（2026-06-11 Round 5 迁移），
本文件只保留请求解析 + 鉴权 + 调 service。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import require_admin
from app.database import get_db
from app.schemas.config import PromptTemplateCreate, PromptTemplateResponse, PromptTemplateUpdate
from app.services.prompt_template_service import PromptTemplateService

router = APIRouter()


@router.get("", response_model=dict)
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """列出全部 Prompt 模板（按创建时间倒序）。"""
    service = PromptTemplateService(db)
    items = await service.list_templates()
    return {"items": [PromptTemplateResponse.model_validate(item) for item in items]}


@router.post("", response_model=PromptTemplateResponse, status_code=201)
async def create_prompt(
    data: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """新建 Prompt 模板（写库后自动失效该 scene 的激活模板缓存）。"""
    service = PromptTemplateService(db)
    return await service.create(data)


@router.put("/{prompt_id}", response_model=PromptTemplateResponse)
async def update_prompt(
    prompt_id: str,
    data: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """更新 Prompt 模板（写库后自动失效缓存）。"""
    service = PromptTemplateService(db)
    return await service.update(prompt_id, data)


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """删除 Prompt 模板（写库后自动失效缓存）。"""
    service = PromptTemplateService(db)
    await service.delete(prompt_id)
