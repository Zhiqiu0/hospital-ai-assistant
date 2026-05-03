"""patient_soft_delete

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-05-03 17:30:00.000000

变更内容：
  patients 表新增 3 列支持「软删除」：
  - is_deleted   : 是否已软删（默认 false，所有查询点过滤）
  - deleted_at   : 软删时间
  - deleted_by   : 触发软删的医生 ID（一般 = 取消接诊的操作者）

业务背景：
  接诊取消（encounters.status='cancelled'）后，如果该患者档案是这次接诊
  时一并新建（且非 HIS 来源、且无其他 encounter），则该档案视为孤儿数据，
  应连带软删，避免 sadasdsa 这种"取消了仍能被搜出来"的语义错乱。
  老患者（有 completed 接诊或 HIS 同步）的复诊取消则不动 patient.is_deleted。

为什么用软删而非物理删：
  - 医疗合规要求审计留痕，物理删后无回溯；
  - 软删保留 deleted_at/deleted_by 后续可做"档案恢复"或"批量归档"运维动作。

幂等：
  跟历史 migration 一致，列已存在则跳过（兼容 migrate.py 兜底场景）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("patients")}

    if "is_deleted" not in existing_cols:
        op.add_column(
            "patients",
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )
    if "deleted_at" not in existing_cols:
        op.add_column(
            "patients",
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
    if "deleted_by" not in existing_cols:
        op.add_column(
            "patients",
            sa.Column(
                "deleted_by",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
        )

    # 已有数据全部默认 is_deleted=false（add_column 时 server_default 已生效，
    # 但显式 UPDATE 一次防止旧版本 alembic 在某些场景下不回填）
    op.execute("UPDATE patients SET is_deleted = false WHERE is_deleted IS NULL")


def downgrade() -> None:
    op.drop_column("patients", "deleted_by")
    op.drop_column("patients", "deleted_at")
    op.drop_column("patients", "is_deleted")
