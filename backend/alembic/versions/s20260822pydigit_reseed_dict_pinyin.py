# -*- coding: utf-8 -*-
"""字典换版重导：拼音首字母保留数字（阶段2 修订）

Revision ID: s20260822pydigit
Revises: r20260821qcrev
Create Date: 2026-08-22

为什么：旧构建脚本的拼音生成丢掉非汉字字符——"2型糖尿病"的检索串是
"xtnb"，医生按直觉输 "2xtnb" 永远搜不到（终验实锤）。构建脚本已修
（数字/字母原样保留），本迁移按既定换版机制清表重导新 CSV。

幂等：抽查 "2型糖尿病" 的拼音串已含数字则跳过（重跑安全）。
"""
import csv
import gzip
from pathlib import Path
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "s20260822pydigit"
down_revision: Union[str, None] = "r20260821qcrev"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CSV = Path(__file__).resolve().parents[2] / "seed_data" / "diagnosis_codes.csv.gz"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "diagnosis_codes" not in inspector.get_table_names():
        return  # 表由 q20260821dict 建；不存在说明还没跑到那步（顺序上不可能）
    # 幂等探针：新版拼音串带数字
    probe = bind.execute(sa.text(
        "SELECT pinyin_initial FROM diagnosis_codes WHERE name='2型糖尿病' LIMIT 1"
    )).scalar()
    if probe and any(c.isdigit() for c in probe):
        return
    if not _CSV.exists():
        return

    bind.execute(sa.text("DELETE FROM diagnosis_codes"))
    with gzip.open(_CSV, "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    table = sa.table(
        "diagnosis_codes",
        sa.column("id"), sa.column("code"), sa.column("name"),
        sa.column("code_type"), sa.column("pinyin_initial"),
        sa.column("aliases"), sa.column("version"),
    )
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
    # 数据修订不可逆回滚（旧拼音串无保留价值）；表结构不变
    pass
