"""
审计日志服务 — 在关键操作后调用 log_action() 记录操作日志
"""
import logging

from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog


logger = logging.getLogger(__name__)


async def log_action(
    action: str,
    user_id: str | None = None,
    user_name: str | None = None,
    user_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
    status: str = "ok",
):
    """Write an audit log entry using a fresh DB session (fire-and-forget safe)."""
    async with AsyncSessionLocal() as db:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            user_name=user_name,
            user_role=user_role,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            ip_address=ip_address,
            status=status,
        )
        db.add(entry)
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Failed to write audit log", extra={"action": action, "resource_type": resource_type})
