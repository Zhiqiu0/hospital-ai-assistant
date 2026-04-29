"""patient_pinyin_index

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-29 00:00:00.000000

变更内容：
  patients 表新增两列拼音索引 + 一次性回填存量数据
  - name_pinyin          : 全拼/首字母/混拼组合，主战场（ILIKE 查询）
  - name_pinyin_initials : 仅纯首字母组合（备用）

为什么放在 upgrade 里回填：
  存量患者列建好就空着没法被拼音搜到，必须回填。在 migration 里执行
  保证一次部署到位，无需额外脚本（部署流程一律 alembic upgrade head）。

回填实现：
  纯 SQL 没法算拼音，只能用 Python 调 utils.pinyin.compute_pinyin。
  迁移内 import 业务工具看似耦合，但患者表规模小（万级），跑一次足够。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 加列（幂等：列已存在则跳过——兼容 migrate.py 兜底先 ALTER 过的场景）
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("patients")}
    if "name_pinyin" not in existing_cols:
        op.add_column(
            "patients",
            sa.Column("name_pinyin", sa.String(512), nullable=True),
        )
    if "name_pinyin_initials" not in existing_cols:
        op.add_column(
            "patients",
            sa.Column("name_pinyin_initials", sa.String(128), nullable=True),
        )

    # 2. 回填存量数据（仅对 name_pinyin 仍 NULL 的患者计算，幂等不重写已有值）
    # 注意：这里 import 业务工具是为了一次性数据迁移，不是常规 migration 模式。
    # 患者表规模通常在万级，单次 migration 可以接受；后续 create/update 由 service 层维护。
    from app.utils.pinyin import compute_pinyin

    rows = bind.execute(
        sa.text("SELECT id, name FROM patients WHERE name_pinyin IS NULL")
    ).fetchall()
    for row in rows:
        pinyin_full, pinyin_initials = compute_pinyin(row.name or "")
        bind.execute(
            sa.text(
                "UPDATE patients SET name_pinyin = :full, name_pinyin_initials = :init WHERE id = :id"
            ),
            {"full": pinyin_full, "init": pinyin_initials, "id": row.id},
        )


def downgrade() -> None:
    op.drop_column("patients", "name_pinyin_initials")
    op.drop_column("patients", "name_pinyin")
