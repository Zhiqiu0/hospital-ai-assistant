"""
审计日志服务（app/services/audit_service.py）

职责：
  提供 log_action() 异步函数，在关键业务操作后记录操作日志到 audit_logs 表。

设计要点：
  1. Fire-and-forget 安全：使用独立 AsyncSessionLocal 会话，不依赖请求的 db 会话。
     即使请求会话已关闭或回滚，审计日志仍可独立写入。
  2. 静默失败：commit 失败时只记录本地日志（logger.exception），
     不向上层抛出异常，防止审计失败影响正常业务流程。
  3. 由路由层或服务层在关键操作完成后调用（如登录、签发病历、修改用户等）。

典型调用示例：
    await log_action(
        action="login",
        user_id=user["id"],
        user_name=user["username"],
        user_role=user["role"],
        ip_address=request.client.host,
        status="ok",
    )
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
    """记录一条操作审计日志。

    使用独立数据库会话写入，不与请求会话耦合，适合在任何时机调用（包括请求处理完成后）。

    Args:
        action:        操作类型，如 "login"、"quick_save"、"create_user" 等。
        user_id:       操作用户的 UUID（未登录操作可为 None）。
        user_name:     操作用户的用户名（冗余存储，防止用户被删除后日志失去可读性）。
        user_role:     操作用户角色（"doctor" / "admin"），用于按角色过滤审计记录。
        resource_type: 操作对象类型，如 "encounter"、"medical_record"、"user" 等。
        resource_id:   操作对象的 UUID，与 resource_type 合用可定位具体记录。
        detail:        操作详情的自由文本描述（如错误原因、关键参数摘要）。
        ip_address:    请求来源 IP（从 request.client.host 获取），用于安全审计。
        status:        操作结果："ok" 表示成功，"fail" 表示失败（如登录失败）。
    """
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
            # 审计写入失败只记录本地日志，不向业务层抛异常（防止影响主流程）
            logger.exception(
                "Failed to write audit log",
                extra={"action": action, "resource_type": resource_type},
            )
