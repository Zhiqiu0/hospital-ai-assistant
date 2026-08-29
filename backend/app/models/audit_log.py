"""
审计日志 ORM 模型（models/audit_log.py）

数据表：
  audit_logs : 系统操作审计记录，追踪所有关键操作（病历创建、质控、登录等）

用途：
  - 安全审计：追查异常操作（如大量导出、频繁质控失败）
  - 合规要求：医疗系统要求对病历操作留有完整日志
  - 故障排查：通过 action + resource_id 定位某条病历的操作历史

写入说明：
  由 AuditService 统一写入，路由层调用 audit_service.log(...)，
  不直接操作此表，确保日志格式一致。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import generate_uuid


class AuditLog(Base):
    """操作审计日志表。

    没有继承 TimestampMixin（只有 created_at，不需要 updated_at，日志不可修改）。
    """

    __tablename__ = "audit_logs"

    # 2026-08-14 第七轮审计：本表零索引。它是全库写入最频繁的表（每次 PHI 查阅
    # 都落一行），而管理端列表固定 ORDER BY created_at DESC 分页——无索引时
    # 每翻一页都要全表排序，随着审计量增长会先拖垮管理端、再拖累写入。
    # 归属校验放开后审计是唯一的追责手段，这张表必须一直可用。
    __table_args__ = (
        Index("idx_audit_logs_created", "created_at"),
        # 按行为类型筛选时的复合索引（管理端 action 下拉）
        Index("idx_audit_logs_action_created", "action", "created_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 操作发生时间（数据库 now()，不依赖应用服务器时间，更准确）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # ── 操作者信息 ────────────────────────────────────────────────────────────
    # user_id 可空：系统自动任务（如定时质控）没有操作用户
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # 冗余存储用户名（避免用户改名后查不到操作者）
    user_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 操作时的角色（用户角色可能变化，记录操作时的角色）
    user_role: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── 操作内容 ──────────────────────────────────────────────────────────────
    # 操作类型，如："login" / "create_record" / "qc_run" / "export_word"
    # 200 而非 50（2026-08-29 收尾轮）：admin 路由级审计的 action 是
    # "admin:{method}:{path}" 拼接，长路径（rubrics 详情/reset-password）
    # 超 50 → 插入失败被 log_action 静默吞掉——那些操作**从未被审计**，
    # 等保审计链有洞且测试库(SQLite 不校验列宽)测不出来。
    action: Mapped[str] = mapped_column(String(200))
    # 操作的资源类型，如："patient" / "medical_record" / "user"
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 操作的具体资源 ID（UUID）
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # 操作详情（JSON 字符串或自然语言描述，存储操作前后的关键数据差异）
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── 请求上下文 ────────────────────────────────────────────────────────────
    # 客户端 IP 地址（含 X-Forwarded-For 代理 IP）
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 操作结果："ok"（成功）/ "error"（失败，detail 中有错误信息）
    status: Mapped[str] = mapped_column(String(10), default="ok")
