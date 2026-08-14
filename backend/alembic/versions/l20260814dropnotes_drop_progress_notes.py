"""删除 progress_notes 表（住院文书统一到 medical_records）

Revision ID: l20260814dropnotes
Revises: k20260814recat
Create Date: 2026-08-14

为什么删（第八轮审计 + 行业标准调研的结论）：

  住院时间轴上的「新建文书」按钮原先建的是 progress_notes，而编辑器下拉建的是
  medical_records。同一件事两条路，医生完全看不出区别——两边界面都显示
  「已签发」，但走 progress_notes 那条：
    · 不回写 HIS（法定病案里一个字都没有）
    · 不进任何病历列表（患者历史、管理后台都看不到）
    · 无版本、无签名链（直接改库无痕）
    · 不参与质控评分与时效合规
  这不是配置差异，是两张互不相通的表。

  HL7 FHIR 的做法是所有临床文书**统一一个文档模型**（Composition /
  DocumentReference），靠 type 码区分种类，而不是每种文书一张表——
  medical_records 的 (record_type + record_no) 正是这个形状。

  故：时间轴改为建 medical_records，progress_notes 就此没有任何入口，
  留着只会是第二条随时可能被误用的路。

存量数据：生产上本表 **0 行**（已实测确认），无需迁移。
故直接删表；有数据的环境请先自行导出，本迁移不做数据搬运。

幂等：先判表是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l20260814dropnotes"
down_revision: Union[str, None] = "k20260814recat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "progress_notes" not in inspector.get_table_names():
        return
    op.drop_table("progress_notes")


def downgrade() -> None:
    """回滚只重建空表结构——原数据无法恢复（本就应为空）。"""
    inspector = sa.inspect(op.get_bind())
    if "progress_notes" in inspector.get_table_names():
        return
    op.create_table(
        "progress_notes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("encounter_id", sa.String(), nullable=False, index=True),
        sa.Column("note_type", sa.String(30)),
        sa.Column("title", sa.String(200)),
        sa.Column("content", sa.Text()),
        sa.Column("recorded_at", sa.DateTime()),
        sa.Column("recorded_by", sa.String(50)),
        sa.Column("status", sa.String(20)),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )
