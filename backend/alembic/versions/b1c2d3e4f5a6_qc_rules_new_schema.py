"""qc_rules_new_schema

Revision ID: b1c2d3e4f5a6
Revises: ad93f93fec62
Create Date: 2026-04-16 00:00:00.000000

变更内容：
  qc_rules 表结构升级，支持 DB 驱动规则引擎
  - 新增：rule_code, scope, keywords, indication_keywords, issue_description, suggestion, score_impact
  - 删除：condition（已被 keywords + indication_keywords 替代）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from typing import Sequence, Union

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "ad93f93fec62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 删除已废弃的 condition 字段
    op.drop_column("qc_rules", "condition")

    # 旧规则数据无迁移价值（将由 seed_config.py 重新填充），先清空
    op.execute("TRUNCATE TABLE qc_rules")

    # 新增规则编码（唯一，不为空）
    op.add_column(
        "qc_rules",
        sa.Column("rule_code", sa.String(length=20), nullable=False, server_default=""),
    )
    op.create_unique_constraint("uq_qc_rules_rule_code", "qc_rules", ["rule_code"])
    # 移除临时 server_default
    op.alter_column("qc_rules", "rule_code", server_default=None)

    # 新增 scope 字段（适用范围）
    op.add_column(
        "qc_rules",
        sa.Column("scope", sa.String(length=20), server_default="all", nullable=False),
    )

    # 新增关键词 JSON 数组
    op.add_column(
        "qc_rules",
        sa.Column("keywords", sa.JSON(), nullable=True),
    )
    op.add_column(
        "qc_rules",
        sa.Column("indication_keywords", sa.JSON(), nullable=True),
    )

    # 新增问题描述与建议（原来仅有 name / description）
    op.add_column(
        "qc_rules",
        sa.Column("issue_description", sa.Text(), nullable=True),
    )
    op.add_column(
        "qc_rules",
        sa.Column("suggestion", sa.Text(), nullable=True),
    )
    op.add_column(
        "qc_rules",
        sa.Column("score_impact", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("qc_rules", "score_impact")
    op.drop_column("qc_rules", "suggestion")
    op.drop_column("qc_rules", "issue_description")
    op.drop_column("qc_rules", "indication_keywords")
    op.drop_column("qc_rules", "keywords")
    op.drop_column("qc_rules", "scope")
    op.drop_constraint("uq_qc_rules_rule_code", "qc_rules", type_="unique")
    op.drop_column("qc_rules", "rule_code")
    op.add_column(
        "qc_rules",
        sa.Column("condition", sa.Text(), nullable=True),
    )
