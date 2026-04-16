"""
管理后台质控规则接口（/api/v1/admin/qc-rules/*）

管理规则引擎使用的质控规则配置（DB 驱动，独立于 LLM prompt）。
规则变更实时生效：规则引擎每次执行时从 DB 实时加载激活规则。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import require_admin
from app.database import get_db
from app.models.config import QCRule
from app.schemas.config import QCRuleCreate, QCRuleResponse, QCRuleUpdate

router = APIRouter()


@router.get("", response_model=dict)
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """列出所有质控规则，按 rule_code 升序排列。"""
    result = await db.execute(select(QCRule).order_by(QCRule.rule_code))
    items = result.scalars().all()
    return {"items": [QCRuleResponse.model_validate(item) for item in items]}


@router.post("", response_model=QCRuleResponse, status_code=201)
async def create_rule(
    data: QCRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """新增质控规则。rule_code 需全局唯一。"""
    rule = QCRule(**data.model_dump())
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
    """更新质控规则字段（仅更新传入的非 None 字段）。"""
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
    """切换质控规则的启用/停用状态。"""
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
    """删除质控规则（不可恢复，建议改用 toggle 停用）。"""
    result = await db.execute(select(QCRule).where(QCRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="QC rule not found")
    await db.delete(rule)
    await db.commit()
