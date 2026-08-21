# -*- coding: utf-8 -*-
"""新增 qc_reviews 病历复核记录表（阶段4 科室质控员）

Revision ID: r20260821qcrev
Revises: q20260821dict
Create Date: 2026-08-21

病案首页质控方案的三级体系（院-科-人）中"科室质控员 24h 复核签字"的电子化
落点。幂等：表存在跳过。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r20260821qcrev"
down_revision: Union[str, None] = "q20260821dict"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "qc_reviews" in inspector.get_table_names():
        return
    op.create_table(
        "qc_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "medical_record_id", sa.String(), sa.ForeignKey("medical_records.id"), nullable=False
        ),
        sa.Column("encounter_id", sa.String(), sa.ForeignKey("encounters.id"), nullable=True),
        sa.Column("reviewer_id", sa.String(), nullable=False),
        sa.Column("reviewer_name", sa.String(50), nullable=True),
        sa.Column("conclusion", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_qc_reviews_record", "qc_reviews", ["medical_record_id", "created_at"])
    op.create_index("idx_qc_reviews_enc", "qc_reviews", ["encounter_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "qc_reviews" in inspector.get_table_names():
        op.drop_table("qc_reviews")
