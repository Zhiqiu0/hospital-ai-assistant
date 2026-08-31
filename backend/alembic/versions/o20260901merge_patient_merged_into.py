# -*- coding: utf-8 -*-
"""patients 增加 merged_into（重复档案合并追溯）

Revision ID: o20260901merge
Revises: n20260831medrecidx
Create Date: 2026-09-01

为什么：老人无身份证、儿童留家长手机、代挂号——查重强键全 miss 时系统会新建
档案，代码里三处注释都写着「重复档案**可事后人工合并**」（encounters_quickstart、
admit_service、_patient_query 的 find_existing），而合并功能一直不存在。后果是
既往史/过敏史/影像/检验分散在两份档案下，医生查复诊史只看得到一半——过敏史
正是开药前工作台飘红警示的那个字段。

合并是**不可逆**操作（代码注释原话："误合并两个人不可逆"），所以必须留下明确
的追溯链：被合并掉的那份档案软删后，本列指向它被并进了哪一份。仅靠 audit_logs
不够——审计是按时间线查的，而这里需要的是"打开这份空档案时立刻知道它去哪了"。

幂等：ADD COLUMN IF NOT EXISTS。可空、无默认值，不重写表。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o20260901merge"
down_revision: Union[str, None] = "n20260831medrecidx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite 测试库由 metadata.create_all 按模型建
    bind.execute(sa.text(
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS merged_into VARCHAR"
    ))
    # 查"这份档案被并到哪了"以及"哪些档案并进了我"都要走它，且合并后的档案
    # 会长期存在，建个索引免得将来全表扫。部分索引：绝大多数档案没被合并过。
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_patients_merged_into "
        "ON patients (merged_into) WHERE merged_into IS NOT NULL"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_patients_merged_into"))
    bind.execute(sa.text("ALTER TABLE patients DROP COLUMN IF EXISTS merged_into"))
