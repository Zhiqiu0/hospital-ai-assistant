from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.database import get_db
from app.core.security import require_admin
from app.models.audit_log import AuditLog

router = APIRouter()


@router.get("")
async def list_audit_logs(
    keyword: str = Query(default="", description="搜索用户名或操作"),
    action: str = Query(default="", description="操作类型过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if keyword:
        query = query.where(
            or_(
                AuditLog.user_name.ilike(f"%{keyword}%"),
                AuditLog.action.ilike(f"%{keyword}%"),
                AuditLog.detail.ilike(f"%{keyword}%"),
            )
        )
    if action:
        query = query.where(AuditLog.action == action)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    items = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "created_at": str(item.created_at) if item.created_at else None,
                "user_name": item.user_name,
                "user_role": item.user_role,
                "action": item.action,
                "resource_type": item.resource_type,
                "resource_id": item.resource_id,
                "detail": item.detail,
                "ip_address": item.ip_address,
                "status": item.status,
            }
            for item in items
        ],
    }
