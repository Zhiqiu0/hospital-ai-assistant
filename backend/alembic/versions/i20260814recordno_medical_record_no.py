"""medical_records.record_no（住院同类型多份文书区分）

Revision ID: i20260814recordno
Revises: h20260814veruniq
Create Date: 2026-08-14

为什么需要（2026-08-14 第六轮审计发现）：
  住院一次接诊天然有**多份同类型文书**——日常病程、上级查房、术后病程都会写好
  几份。而定位病历一直只按 (encounter_id, record_type) 取最近更新的一行，
  第二份病程直接覆盖第一份：医生前一天写的病程被今天这份顶掉，内容永久丢失。

  HIS 接口规范里早就预留了 record_no 用于区分多份文书（幂等键=visit_id +
  record_type + record_no），但后端从来没实现——全仓 grep 只有注释提到过它。

存量数据：门急诊一次接诊一份文书，住院此前也只可能存在一份（多的那些已经被
覆盖掉了），所以全部回填为 1 即正确，不需要复杂的重排。

幂等：先判列是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i20260814recordno"
down_revision: Union[str, None] = "h20260814veruniq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("medical_records")}
    if "record_no" in cols:
        return
    # 先加可空列并回填，再收紧为 NOT NULL——存量表非空加列必须给默认值
    op.add_column(
        "medical_records",
        sa.Column("record_no", sa.Integer(), nullable=False, server_default="1"),
    )
    # 去掉 server_default：新行的默认值由 ORM 的 default=1 提供，
    # 保留 server_default 会让 alembic check 报漂移（模型侧没声明它）
    op.alter_column("medical_records", "record_no", server_default=None)


def downgrade() -> None:
    op.drop_column("medical_records", "record_no")
