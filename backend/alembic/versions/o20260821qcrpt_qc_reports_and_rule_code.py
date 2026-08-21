# -*- coding: utf-8 -*-
"""新增 qc_reports 评分报告表 + qc_issues.rule_code 列（阶段0 质控落库收口）

Revision ID: o20260821qcrpt
Revises: n20260818dropaicfg
Create Date: 2026-08-21

为什么加：

  病案首页质控方案要求月度通报"科室合格率/主要诊断正确率/典型缺陷"，但此前：
    · 评分（score/grade）只走 SSE 给前端，完全不落库——库里无数可统计；
    · 扣分条款代码（rule_code）在落 qc_issues 时被丢弃——"最高频扣分条款
      Top 榜"做不了，只能退化到粒度混乱的 field_name；
    · qc_issues 只在 LLM 成功后才写，LLM 一挂整次质控零痕迹。

  qc_reports = 一次法定评分的权威"表头"（分数/等级/全部扣分明细 JSONB +
  科室/医生冗余快照），在规则引擎评分完成瞬间落库，与 LLM 成败无关。
  qc_issues 保持"明细流水"语义不变，仅补 rule_code 列。

幂等：先判表/列是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "o20260821qcrpt"
down_revision: Union[str, None] = "n20260818dropaicfg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── qc_reports 表 ────────────────────────────────────────────────
    if "qc_reports" not in inspector.get_table_names():
        op.create_table(
            "qc_reports",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("encounter_id", sa.String(), sa.ForeignKey("encounters.id"), nullable=True),
            sa.Column(
                "medical_record_id", sa.String(), sa.ForeignKey("medical_records.id"), nullable=True
            ),
            sa.Column("record_type", sa.String(30), nullable=False),
            sa.Column("rubric_key", sa.String(50), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("grade", sa.String(10), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("deductions", JSONB, nullable=True),
            sa.Column("department_id", sa.String(), nullable=True),
            sa.Column("doctor_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index(
            "idx_qc_reports_enc", "qc_reports", ["encounter_id", "record_type", "created_at"]
        )
        op.create_index("idx_qc_reports_dept", "qc_reports", ["department_id", "created_at"])

    # ── qc_issues.rule_code 列 ───────────────────────────────────────
    issue_cols = {c["name"] for c in inspector.get_columns("qc_issues")}
    if "rule_code" not in issue_cols:
        op.add_column("qc_issues", sa.Column("rule_code", sa.String(40), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "qc_reports" in inspector.get_table_names():
        op.drop_table("qc_reports")
    issue_cols = {c["name"] for c in inspector.get_columns("qc_issues")}
    if "rule_code" in issue_cols:
        op.drop_column("qc_issues", "rule_code")
