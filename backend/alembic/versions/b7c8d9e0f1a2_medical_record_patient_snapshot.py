"""medical_record_patient_snapshot

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-05-16 18:00:00.000000

变更内容：
  medical_records 表新增 patient_snapshot JSONB 列，签发瞬间冻结患者完整身份
  字段（姓名/性别/出生日期/身份证/电话/住址/民族/婚姻/职业/工作单位/紧急联系人 +
  接诊医生/科室/就诊时间）。

业务背景（合规级要求）：
  之前病历正文（content）和患者身份（patient 表）是两张表分别存。当医生后续
  改了患者档案的电话/住址时，**已签发**病历也会跟着变——这违反医疗病案的
  不可篡改原则。本字段把签发瞬间的患者完整信息冻结到病历记录里，未来 patient
  表的更新不再影响已签发病历的展示。

  UI 渲染策略：
    未签发病历首页 → 从 patient 表实时读（保持最新）
    已签发病历首页 → 从 patient_snapshot 读（永久冻结）

旧数据兼容：
  字段 nullable=True，老病历此字段为 NULL；前端 fallback 到当前 patient
  表保证不报错。新签发的病历必有 snapshot。

幂等：
  列已存在则跳过（兼容 migrate.py 兜底脚本）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("medical_records")}

    if "patient_snapshot" not in existing_cols:
        op.add_column(
            "medical_records",
            sa.Column(
                "patient_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column("medical_records", "patient_snapshot")
