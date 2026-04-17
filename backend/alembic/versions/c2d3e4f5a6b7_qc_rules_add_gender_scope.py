"""qc_rules_add_gender_scope

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-17 00:00:00.000000

变更内容：
  qc_rules 表新增 gender_scope 字段，支持按患者性别过滤规则
  - all    : 不限性别（默认）
  - female : 仅女性患者触发（如月经史缺失）
  - male   : 仅男性患者触发
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "qc_rules",
        sa.Column(
            "gender_scope",
            sa.String(10),
            nullable=False,
            server_default="all",
        ),
    )


def downgrade() -> None:
    op.drop_column("qc_rules", "gender_scope")
