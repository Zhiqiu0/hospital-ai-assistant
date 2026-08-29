# -*- coding: utf-8 -*-
"""audit_logs.action 加宽 50→200（2026-08-29 收尾轮日志实况审查）

Revision ID: m20260829auditwiden
Revises: l20260829idxgap
Create Date: 2026-08-29

为什么：admin 路由级审计的 action 形如 "admin:{method}:{path}"，长路径
（/api/v1/admin/rubrics/zj_outpatient_emergency_2023、users/{uuid}/reset-password）
超过 varchar(50) → INSERT 报 StringDataRightTruncationError，被 log_action 的
兜底静默吞掉——这些管理操作**从未被审计过**（生产 error.log 实锤），等保
审计链有洞。SQLite 测试库不校验列宽所以 CI 一直绿。

varchar 加宽在 PG 是元数据操作不重写表、不受 audit_logs 只追加触发器影响
（触发器只拦行级 UPDATE/DELETE）。幂等：重复执行同类型 ALTER 无害。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m20260829auditwiden"
down_revision: Union[str, None] = "l20260829idxgap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite 测试库由 metadata.create_all 按模型建（已是 200）
    bind.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN action TYPE VARCHAR(200)"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # 回退前截断存量超长值，避免收窄失败。audit_logs 挂只追加触发器
    # （trg_audit_logs_append_only 拦 UPDATE），同事务临时禁用再恢复
    # ——与 purge_clinical_data 的既有口径一致。
    bind.execute(sa.text(
        "ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only"))
    bind.execute(sa.text(
        "UPDATE audit_logs SET action = LEFT(action, 50) WHERE LENGTH(action) > 50"))
    bind.execute(sa.text(
        "ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only"))
    bind.execute(sa.text(
        "ALTER TABLE audit_logs ALTER COLUMN action TYPE VARCHAR(50)"))
