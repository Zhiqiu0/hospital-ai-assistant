# -*- coding: utf-8 -*-
"""热路径索引补缺（2026-08-29 第四轮对抗复核）

Revision ID: l20260829idxgap
Revises: k20260828integrity
Create Date: 2026-08-29

为什么：对抗复核发现三条随表增长退化为全表扫描的查询，均无索引覆盖：

1. record_versions：质控复核台"最新管理员修订时间"子查询与删除横幅整改判据
   都按 source='admin_revise' 过滤后按 medical_record_id 聚合/EXISTS。
   修订版本占比极小 → 部分索引。
2. ai_tasks：删除病历时 UPDATE ... WHERE medical_record_id = X 解挂任务。
   大部分任务不挂病历（NULL）→ 部分索引只存非空行。
3. qc_reports：删除病历前"有无质控报告"探测按 medical_record_id 等值查。
   同上用部分索引跳过 NULL。

幂等：全部 CREATE INDEX IF NOT EXISTS；SQLite 测试库由 metadata.create_all
按模型定义建索引，此处跳过。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l20260829idxgap"
down_revision: Union[str, None] = "k20260828integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = (
    ("idx_record_versions_admin_revise",
     "record_versions (medical_record_id, created_at) "
     "WHERE source = 'admin_revise'"),
    ("idx_ai_tasks_record",
     "ai_tasks (medical_record_id) WHERE medical_record_id IS NOT NULL"),
    ("idx_qc_reports_record",
     "qc_reports (medical_record_id) WHERE medical_record_id IS NOT NULL"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite 测试库走 metadata.create_all，模型里已带同名索引
    for name, spec in _INDEXES:
        bind.execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {spec}"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, _ in _INDEXES:
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
