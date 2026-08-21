# -*- coding: utf-8 -*-
"""新增 diagnosis_codes 编码字典表 + 自动导入全量字典（阶段2 编码化）

Revision ID: q20260821dict
Revises: p20260821diag
Create Date: 2026-08-21

为什么：

  病案首页质控方案要求诊断编码化（中医病证按分类编码填写、编码准确率指标）；
  DRG 分组以编码为键。字典四类共约 4.8 万条（ICD-10 医保 2.0 / 手术 ICD-9-CM-3 /
  中医病证 GB/T 15657-2021 医保版），构建脚本与数据来源见
  scripts/build_diagnosis_dict.py 头注释（全部官方渠道）。

导入设计：

  数据文件 seed_data/diagnosis_codes.csv.gz 随代码进 git（634KB，字典即代码
  资产，与"评分标准代码化"同一哲学）。迁移里判空表才导入——重跑安全；
  换版字典 = 换 CSV + 新迁移清表重导，可审计可回滚。

幂等：表存在跳过建表；表非空跳过导入。
"""
import csv
import gzip
from pathlib import Path
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "q20260821dict"
down_revision: Union[str, None] = "p20260821diag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CSV = Path(__file__).resolve().parents[2] / "seed_data" / "diagnosis_codes.csv.gz"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "diagnosis_codes" not in inspector.get_table_names():
        op.create_table(
            "diagnosis_codes",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("code", sa.String(40), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("code_type", sa.String(10), nullable=False),
            sa.Column("pinyin_initial", sa.String(60), nullable=True),
            sa.Column("aliases", sa.String(300), nullable=True),
            sa.Column("version", sa.String(20), nullable=False, server_default="医保2.0"),
        )
        op.create_index("idx_diag_codes_type_name", "diagnosis_codes", ["code_type", "name"])
        op.create_index(
            "idx_diag_codes_type_pinyin", "diagnosis_codes", ["code_type", "pinyin_initial"]
        )
        op.create_index("idx_diag_codes_type_code", "diagnosis_codes", ["code_type", "code"])

    # ── 空表才导入（幂等）────────────────────────────────────────────
    count = bind.execute(sa.text("SELECT count(*) FROM diagnosis_codes")).scalar()
    if count and count > 0:
        return
    if not _CSV.exists():
        # 数据文件缺失不阻断迁移（测试环境等）——表建好即可，导入可后补
        return

    with gzip.open(_CSV, "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    table = sa.table(
        "diagnosis_codes",
        sa.column("id"), sa.column("code"), sa.column("name"),
        sa.column("code_type"), sa.column("pinyin_initial"),
        sa.column("aliases"), sa.column("version"),
    )
    # 分批插入，避免单条超大 SQL
    batch = 2000
    for i in range(0, len(rows), batch):
        op.bulk_insert(table, [
            {
                "id": uuid4().hex,
                "code": r["code"],
                "name": r["name"],
                "code_type": r["code_type"],
                "pinyin_initial": r["pinyin_initial"] or None,
                "aliases": r["aliases"] or None,
                "version": "医保2.0",
            }
            for r in rows[i : i + batch]
        ])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "diagnosis_codes" in inspector.get_table_names():
        op.drop_table("diagnosis_codes")
