"""record_version_ai_similarity

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-12 12:00:00.000000

变更内容：
  record_versions 表新增两列（AI 采纳度量，反馈闭环数据管道）：
    ai_similarity      : DOUBLE PRECISION，签发终稿与最近一版 AI 草稿的
                         文本相似度（0~1，difflib.SequenceMatcher.ratio）
    ai_base_version_no : INTEGER，对比基准的 AI 版本号（追溯是哪版草稿）

为什么加在 record_versions 而不另开表：
  相似度是"签发版本"的属性（一次签发对应一个值），version 行天然就是
  落点；纯手写签发（无 AI 版本）两列为 NULL，看板聚合时天然排除。

生产迁移说明：
  生产 alembic 与 migrate.py 双通道并存（deploy 两个都跑），本 revision
  与 migrate.py[13] 兜底步骤等价且互相幂等——谁先跑都不冲突。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("record_versions")}

    # 幂等：列已存在则跳过（兼容 migrate.py 兜底先 ALTER 过的场景）
    if "ai_similarity" not in existing_cols:
        op.add_column("record_versions", sa.Column("ai_similarity", sa.Float(), nullable=True))
    if "ai_base_version_no" not in existing_cols:
        op.add_column(
            "record_versions", sa.Column("ai_base_version_no", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    op.drop_column("record_versions", "ai_base_version_no")
    op.drop_column("record_versions", "ai_similarity")
