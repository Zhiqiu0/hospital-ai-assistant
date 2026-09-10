# -*- coding: utf-8 -*-
"""encounters.visit_no 升级为部分唯一索引（2026-09-10 收敛轮并发审计）

Revision ID: p20260910visitno
Revises: o20260901merge
Create Date: 2026-09-10

为什么：visit_no 是 HIS 接诊推送的幂等真键——process_admit 靠它判"这条推送
是不是已经建过接诊"。此前去重只有 advisory lock + 锁内应用层查重，属于
"单写路径记得加锁"式保护：将来任何新写路径（或锁被误删）都可能悄悄产生
重复接诊，且无数据库兜底。2026-08-28 完整性轮（k20260828integrity）给病历
三元组/患者身份证/工号都补了唯一约束，唯独漏了这个键。

做法：把普通索引 idx_encounters_visit_no 原名升级为部分唯一索引
（WHERE visit_no IS NOT NULL AND status <> 'cancelled'）。谓词排除 cancelled
是业务要求：已取消的接诊不复用（test_admit_cancelled_encounter_not_reused
守着），HIS 重推同 visit_no 必须能建新接诊——真正的不变量是「同一 visit_no
至多一条非取消接诊」，与 admit_service 应用层查重口径一致。手动接诊
visit_no 为 NULL 不受约束。保持原名，模型端 Index 声明同步改。

前置核实（2026-09-10 生产库）：19/117 条有 visit_no，零重复——可安全建唯一。
若未来某环境有存量重复，CREATE UNIQUE INDEX 会直接报错中止迁移（这正是
想要的行为：重复接诊是必须人工处置的数据事故，不能静默放过）。

幂等：先 DROP 旧普通索引再 CREATE IF NOT EXISTS；重复执行安全。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p20260910visitno"
down_revision: Union[str, None] = "o20260901merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite 测试库由 metadata.create_all 按模型建（模型已是唯一索引）
    # 旧普通索引与新唯一索引同名——必须先删再建（IF EXISTS/IF NOT EXISTS 保幂等）
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_encounters_visit_no"))
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_encounters_visit_no "
        "ON encounters (visit_no) "
        "WHERE visit_no IS NOT NULL AND status <> 'cancelled'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_encounters_visit_no"))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_encounters_visit_no ON encounters (visit_no)"
    ))
