"""
管理后台审计日志接口（/api/v1/admin/audit-logs/*）

端点列表：
  GET /  分页查询审计日志（支持用户名/操作类型/详情关键词搜索，按时间倒序）

仅管理员可访问（require_admin）。
日志由 audit_service.log_action() 在关键操作后写入，包含：
  - 登录/登出 (action='login'/'logout')
  - 病历签发 (action='sign_record')
  等操作的用户信息、资源标识和 IP 地址。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.models.audit_log import AuditLog

router = APIRouter()


@router.get("")
async def list_audit_logs(
    keyword: str = Query(default="", description="搜索用户名、操作或详情关键词"),
    action: str = Query(default="", description="按操作类型精确过滤（如 login / sign_record）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """分页查询审计日志，按时间倒序排列。

    支持复合搜索：keyword 同时匹配 user_name / action / detail 三个字段（OR 关系）。
    """
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

    # 先统计总数，再查分页数据
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
