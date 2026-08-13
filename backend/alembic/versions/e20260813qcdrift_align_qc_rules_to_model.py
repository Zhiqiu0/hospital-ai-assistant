"""对齐 qc_rules 真实结构与模型（存量库漂移收口）

Revision ID: e20260813qcdrift
Revises: d20260813codes
Create Date: 2026-08-13

为什么需要这条（2026-08-13 备份恢复演练发现）：
  把生产备份恢复到临时库后跑 `alembic check`，报 qc_rules 漂移——**生产库的
  真实结构与模型对不上，而 CI 完全看不见**。原因：基线 DDL 快照是从模型生成的
  （baseline == model），而生产当年是被 alembic_guard **stamp 到基线（零 DDL）**
  的，它那套早期 migrate.py 建出来的形状原封不动留到了今天，从没被校验过。

具体差异（生产 vs 模型）：
  rule_code           : 可空、无唯一约束  →  模型要求 NOT NULL + UNIQUE
  scope / gender_scope: 可空              →  模型要求 NOT NULL
  condition           : 残留列（早期规则表设计），模型早已没有
  keywords 系两列      : 生产是 jsonb 而模型写 JSON —— 这一项**反过来改模型**
                        （JSONB 支持索引与包含查询，本就是更优类型），迁移把
                        基线建出来的 json 列转成 jsonb，让两边一致

风险评估：改前查过生产数据——43 行，rule_code 无空值无重复、scope/gender_scope
无空值、condition 全为 NULL，因此收紧与删列都不会碰到任何真实数据。

为什么值得改而不是"放宽模型迁就库"（模型里 rule_type/risk_level 就是那么处理的）：
  qc_rules 仍被医保规则引擎实时读取。rule_code 缺唯一约束意味着可以插入重复
  规则码，医生会看到重复的质控问题；这条约束有真实价值，不该为了消漂移而放弃。

幂等：所有操作先判存在/先查数据，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e20260813qcdrift"
down_revision: Union[str, None] = "d20260813codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "qc_rules"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return  # 表不存在（理论上不会）→ 无事可做

    cols = {c["name"]: c for c in inspector.get_columns(TABLE)}

    # 1. 残留列 condition：全为 NULL 才删，有数据则留下不动（宁可留漂移也不丢数据）
    if "condition" in cols:
        leftover = bind.execute(
            sa.text(f"SELECT count(*) FROM {TABLE} WHERE condition IS NOT NULL")
        ).scalar()
        if not leftover:
            op.drop_column(TABLE, "condition")

    # 2. 补 NOT NULL：先兜底填默认值，再收紧，避免存量空值挡住 ALTER
    for col, default in (("scope", "all"), ("gender_scope", "all")):
        if col in cols and cols[col]["nullable"]:
            op.execute(f"UPDATE {TABLE} SET {col} = '{default}' WHERE {col} IS NULL")
            op.alter_column(TABLE, col, nullable=False)

    if "rule_code" in cols and cols["rule_code"]["nullable"]:
        # rule_code 没有可用默认值，只在确无空值时才收紧
        nulls = bind.execute(
            sa.text(f"SELECT count(*) FROM {TABLE} WHERE rule_code IS NULL")
        ).scalar()
        if not nulls:
            op.alter_column(TABLE, "rule_code", nullable=False)

    # 3. keywords / indication_keywords 收敛到 jsonb
    #    生产本来就是 jsonb（模型写成 JSON 才是错的，已改模型）；CI 从基线建出来的
    #    库是 json，这里把它转过去，两边一致后 alembic check 才干净。
    for col in ("keywords", "indication_keywords"):
        if col in cols and cols[col]["type"].__class__.__name__ == "JSON":
            op.execute(
                f"ALTER TABLE {TABLE} ALTER COLUMN {col} TYPE jsonb USING {col}::jsonb"
            )

    # 4. rule_code 唯一约束：模型写的是 unique=True（无 index=True），
    #    SQLAlchemy 渲染为 UNIQUE 约束而非唯一索引，这里照抄它的渲染方式，
    #    否则 alembic check 仍会判漂移（本项目 d20260813codes 踩过同款坑）。
    existing_uniques = {u["name"] for u in inspector.get_unique_constraints(TABLE)}
    if "qc_rules_rule_code_key" not in existing_uniques:
        dups = bind.execute(sa.text(
            f"SELECT count(*) FROM (SELECT rule_code FROM {TABLE} "
            "GROUP BY rule_code HAVING count(*) > 1) d"
        )).scalar()
        if not dups:
            op.create_unique_constraint("qc_rules_rule_code_key", TABLE, ["rule_code"])


def downgrade() -> None:
    op.drop_constraint("qc_rules_rule_code_key", TABLE, type_="unique")
    op.alter_column(TABLE, "rule_code", nullable=True)
    op.alter_column(TABLE, "gender_scope", nullable=True)
    op.alter_column(TABLE, "scope", nullable=True)
    op.add_column(TABLE, sa.Column("condition", sa.String(length=200), nullable=True))
