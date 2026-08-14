"""medical_records.recorded_at（临床相关时间，与系统录入时间分离）

Revision ID: k20260814recat
Revises: j20260814hotidx
Create Date: 2026-08-14

为什么需要（第八轮审计后按行业标准统一文书模型）：

  住院病程原先走的是另一张表 progress_notes，它有医生可填的 recorded_at；
  而正式病历表 medical_records 没有这个字段，只有系统自动记的 submitted_at /
  created_at。要把两条路统一到 medical_records（唯一有版本、签名链、
  HIS 回写、质控的那条），就必须先把「临床相关时间」补进来。

  三方规范一致要求这两个时间分开存：
    · HL7 FHIR：DocumentReference.date 是文档创建时刻，临床相关时间必须
      另用 context.period 表达
    · 《病历书写基本规范》：病程记录"首先标明记录时间"，具体到分钟
    · 医法实务：补记须带当前日期并标注为补记，绝不允许静默回填过去时间

  据此本字段只表达「这份文书对应的诊疗时点」；它与 created_at 的差异
  用于判定并展示「补记」，而不是让人随意改时间线。

存量数据：留空即可。门急诊本就当场书写（按 submitted_at 展示），
住院侧生产上 progress_notes 为 0 行、medical_records 无住院病程，无需回填。

幂等：先判列是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k20260814recat"
down_revision: Union[str, None] = "j20260814hotidx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("medical_records")}
    if "recorded_at" in cols:
        return
    op.add_column(
        "medical_records",
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("medical_records")}
    if "recorded_at" not in cols:
        return
    op.drop_column("medical_records", "recorded_at")
