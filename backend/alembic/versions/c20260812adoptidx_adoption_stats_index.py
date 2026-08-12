"""adoption_stats_index —— AI 采纳看板聚合索引

Revision ID: c20260812adoptidx
Revises: b20260812squash
Create Date: 2026-08-12

变更内容：
  record_versions 加部分索引 idx_record_versions_adoption(created_at)
  WHERE source='doctor_signed' AND ai_similarity IS NOT NULL。

为什么：adoption_stats（质量健康看板）按上述条件聚合，无索引随版本表
增长退化为全表扫描；部分索引只覆盖带采纳指标的签发版本，极小且精准。
与模型 RecordVersion.__table_args__ 声明保持一致。

这是冻结基线（b20260812squash）之后的第一条常规迁移——改模型必须
配套写迁移，CI 的 alembic check 门禁会校验两边一致。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c20260812adoptidx"
down_revision: Union[str, None] = "b20260812squash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "idx_record_versions_adoption"


def upgrade() -> None:
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS {_INDEX}
        ON record_versions (created_at)
        WHERE source = 'doctor_signed' AND ai_similarity IS NOT NULL
    """)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
