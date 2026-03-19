from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.core.security import require_admin
from app.models.config import PromptTemplate
from app.schemas.config import PromptTemplateCreate, PromptTemplateUpdate, PromptTemplateResponse

router = APIRouter()


@router.get("", response_model=dict)
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(PromptTemplate).order_by(PromptTemplate.created_at.desc()))
    items = result.scalars().all()
    return {"items": [PromptTemplateResponse.model_validate(item) for item in items]}


@router.post("", response_model=PromptTemplateResponse, status_code=201)
async def create_prompt(
    data: PromptTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    template = PromptTemplate(
        name=data.name,
        scene=data.scene,
        content=data.content,
        version=data.version or "v1",
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.put("/{prompt_id}", response_model=PromptTemplateResponse)
async def update_prompt(
    prompt_id: str,
    data: PromptTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(
    prompt_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(PromptTemplate).where(PromptTemplate.id == prompt_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    await db.delete(template)
    await db.commit()
