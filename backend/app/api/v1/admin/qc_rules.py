from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.core.security import require_admin
from app.models.config import QCRule
from app.schemas.config import QCRuleCreate, QCRuleUpdate, QCRuleResponse

router = APIRouter()


@router.get("", response_model=dict)
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(QCRule).order_by(QCRule.created_at.desc()))
    items = result.scalars().all()
    return {"items": [QCRuleResponse.model_validate(item) for item in items]}


@router.post("", response_model=QCRuleResponse, status_code=201)
async def create_rule(
    data: QCRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    rule = QCRule(
        name=data.name,
        description=data.description,
        rule_type=data.rule_type,
        field_name=data.field_name,
        condition=data.condition,
        risk_level=data.risk_level,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=QCRuleResponse)
async def update_rule(
    rule_id: str,
    data: QCRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(QCRule).where(QCRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="QC rule not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.put("/{rule_id}/toggle", response_model=QCRuleResponse)
async def toggle_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(QCRule).where(QCRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="QC rule not found")
    rule.is_active = not rule.is_active
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    result = await db.execute(select(QCRule).where(QCRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="QC rule not found")
    await db.delete(rule)
    await db.commit()
