# -*- coding: utf-8 -*-
"""新增 diagnoses 诊断条目表 + 存量文本诊断回填（阶段1a 诊断结构化）

Revision ID: p20260821diag
Revises: o20260821qcrpt
Create Date: 2026-08-21

为什么加：

  病案首页是 DRG 分组唯一数据源，"主要诊断选择错误"是法定单项否决（扣 10 分）。
  此前诊断散落 inquiry_inputs 三个自由文本列：主诊断靠"第一个非空即主"隐式
  推断、"入院病情"标志无落点、编码无处可挂。本表是诊断的结构化权威源；
  HIS 回写 v1.4 的 diagnoses[]（code/code_type/is_primary）从本表构建。

存量回填：

  把每个接诊最新版 inquiry_inputs 的三列文本转成条目——
    western_diagnosis      → category=western,      is_primary=True（与既有回写
                             builder"西医优先为主"的隐式规则一致，回填不改语义）
    tcm_disease_diagnosis  → category=tcm_disease   （西医空时它为主，同上）
    tcm_syndrome_diagnosis → category=tcm_syndrome
  西医列可能含"1.高血压 2.糖尿病"式多诊断串——回填不做拆分（无可靠分隔约定，
  强拆会造脏数据），整段作一条；医生在新条目编辑器里可自行拆分。
  生产当前仅测试数据，回填风险为零。

幂等：先判表是否存在；回填用 NOT EXISTS 防重复插入。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p20260821diag"
down_revision: Union[str, None] = "o20260821qcrpt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "diagnoses" not in inspector.get_table_names():
        op.create_table(
            "diagnoses",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "encounter_id", sa.String(), sa.ForeignKey("encounters.id"), nullable=False
            ),
            sa.Column("category", sa.String(20), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("code", sa.String(20), nullable=True),
            sa.Column("code_type", sa.String(10), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("admission_condition", sa.String(10), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("added_by", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("idx_diagnoses_enc", "diagnoses", ["encounter_id"])

    # ── 存量回填（幂等：目标接诊已有条目则跳过）────────────────────────
    # 每个接诊取 version 最大的一版 inquiry；三列非空文本各转一条。
    # 主诊断规则与 his_adapter/writeback_builder._build_diagnoses 既有隐式
    # 逻辑逐字一致：西医非空→西医为主；否则中医疾病为主；否则证候为主。
    bind.execute(sa.text("""
        WITH latest AS (
            SELECT DISTINCT ON (encounter_id)
                   encounter_id, western_diagnosis, tcm_disease_diagnosis, tcm_syndrome_diagnosis
            FROM inquiry_inputs
            ORDER BY encounter_id, version DESC
        ),
        expanded AS (
            SELECT encounter_id, 'western' AS category,
                   left(trim(western_diagnosis), 200) AS name,
                   (TRUE) AS primary_candidate, 0 AS sort_order
            FROM latest WHERE coalesce(trim(western_diagnosis), '') <> ''
            UNION ALL
            SELECT encounter_id, 'tcm_disease',
                   left(trim(tcm_disease_diagnosis), 200),
                   (coalesce(trim(western_diagnosis), '') = ''), 0
            FROM latest WHERE coalesce(trim(tcm_disease_diagnosis), '') <> ''
            UNION ALL
            SELECT encounter_id, 'tcm_syndrome',
                   left(trim(tcm_syndrome_diagnosis), 200),
                   (coalesce(trim(western_diagnosis), '') = ''
                    AND coalesce(trim(tcm_disease_diagnosis), '') = ''), 0
            FROM latest WHERE coalesce(trim(tcm_syndrome_diagnosis), '') <> ''
        )
        INSERT INTO diagnoses
            (id, encounter_id, category, name, is_primary, sort_order, created_at, updated_at)
        SELECT md5(random()::text || clock_timestamp()::text)::text,
               e.encounter_id, e.category, e.name, e.primary_candidate, e.sort_order,
               now(), now()
        FROM expanded e
        WHERE NOT EXISTS (
            SELECT 1 FROM diagnoses d WHERE d.encounter_id = e.encounter_id
        )
    """))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "diagnoses" in inspector.get_table_names():
        op.drop_table("diagnoses")
