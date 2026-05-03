"""encounter_cancel

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-03 16:30:00.000000

变更内容：
  encounters 表新增 3 列支持「医生取消接诊」操作：
  - cancel_reason  : 取消理由（必填，前端预设 5 选 + 自由备注）
  - cancelled_at   : 取消时间
  - cancelled_by   : 操作医生 ID（一般 = doctor_id，留独立字段以备值班医生强取场景）

业务背景：
  之前 encounter.status 只有 in_progress / completed 两态，未签发病历就关浏览器
  的接诊永远卡在 in_progress 不能清，且复诊判断只看患者是否存在导致"上次没签
  发也算复诊"的语义错乱。本次加入 cancelled 状态及配套字段，配合后端复诊判断
  改写（用 status='completed' 而非 patient_reused），实现接诊全状态机闭环。

幂等：
  跟历史 migration 一致，列已存在则跳过（兼容 migrate.py 兜底场景）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("encounters")}

    if "cancel_reason" not in existing_cols:
        op.add_column(
            "encounters",
            sa.Column("cancel_reason", sa.String(500), nullable=True),
        )
    if "cancelled_at" not in existing_cols:
        op.add_column(
            "encounters",
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        )
    if "cancelled_by" not in existing_cols:
        op.add_column(
            "encounters",
            sa.Column(
                "cancelled_by",
                sa.String(),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("encounters", "cancelled_by")
    op.drop_column("encounters", "cancelled_at")
    op.drop_column("encounters", "cancel_reason")
