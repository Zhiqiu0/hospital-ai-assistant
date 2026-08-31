# -*- coding: utf-8 -*-
"""medical_records 补 status/submitted_at 热路径索引（2026-08-31 数据规模审计）

Revision ID: n20260831medrecidx
Revises: m20260829auditwiden
Create Date: 2026-08-31

为什么：生产库现在几乎是空的，所有功能都只在「零数据」下验证过。本轮按
「运行一年、约 10 万份病历」推演，三条高频查询撞在同一个缺口上——
medical_records 只有两个以 encounter_id 打头的索引，**status 与 submitted_at
从未建过索引**（此前第 7、9 轮已给 audit_logs/encounters/ai_tasks/record_versions
补齐热路径索引，唯独漏了这张核心表）：

  · qc/reviews.py  质控复核台待复核清单 —— WHERE status='submitted'，
    且这条查询**没有时间窗兜底**，会一年比一年慢，最终顶到超时；
  · admin_record_service.list_all_records 全院病历列表 ——
    WHERE status='submitted' ORDER BY submitted_at DESC，无索引时每次翻页
    （包括第 1 页）都要排序全部匹配行；
  · inpatient_service 病区列表 —— 子查询 WHERE status <> 'submitted'，
    这是住院医生进入接诊的唯一入口，每次打开都要扫。

两个索引分别针对两类形态：

  ① idx_medrec_status_submitted (status, submitted_at DESC)
     支持「已签发 + 按签发时间倒序取前 N 条」，PG 可直接沿索引取头部，
     不必排序全表。注意 status='submitted' 本身选择性很差（运行一年后绝大
     多数行都是这个终态），单列 status 索引优化器多半不会用——把
     submitted_at 带进来才有意义。

  ② idx_medrec_pending 部分索引，(encounter_id) WHERE status <> 'submitted'
     不等值查询用不上普通 B-tree，但「未签发的草稿」在任何时刻都只是极少数，
     部分索引因此又小又精准，正好服务病区列表那个子查询。

幂等：CREATE INDEX IF NOT EXISTS。用 CONCURRENTLY 需脱离事务，考虑到当前表
几乎是空的、锁表时间可忽略，这里用普通建法保持迁移的事务性。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n20260831medrecidx"
down_revision: Union[str, None] = "m20260829auditwiden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite 测试库由 metadata.create_all 按模型建
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_medrec_status_submitted "
        "ON medical_records (status, submitted_at DESC)"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_medrec_pending "
        "ON medical_records (encounter_id) WHERE status <> 'submitted'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_medrec_pending"))
    bind.execute(sa.text("DROP INDEX IF EXISTS idx_medrec_status_submitted"))
