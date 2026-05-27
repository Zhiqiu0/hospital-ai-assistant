"""encounter_his_external_ref

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-27 13:00:00.000000

变更内容：
  encounters 表新增 his_external_ref JSONB 列，记录嵌入模式接诊关联的
  HIS 患者标识。普通 SaaS 接诊该字段为 NULL，不影响现有数据。

为什么不另开 his_sessions 表：
  嵌入模式本质上是"医生在 HIS 工作流里发起的一次接诊"——跟普通 SaaS 接诊
  唯一差异是"病历最终去向是 HIS"而不是"自己归档"。复用 encounter +
  medical_record 表能让 AI 生成 / 质控 / 审计 / 历史查询所有现有逻辑零
  改动直接复用，省一半代码量，避免数据模型重复。

字段结构（JSONB）：
  {
    "his_brand": "jinsuanpan",
    "hospital_code": "H33052300957",
    "his_patient_no": "Y1232605260025",
    "his_visit_no": "20260526000200",
    "his_doctor_no": "DOC123"
  }

加 GIN 索引：
  常见查询场景是"按 HIS 患者编号回查接诊"（医生在 HIS 切回来想看上次
  AI 写的病历），用 GIN 索引 his_patient_no 路径。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COL_NAME = "his_external_ref"
_IDX_NAME = "idx_encounters_his_patient_no"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("encounters")}

    # 幂等：列已存在则跳过（兼容 migrate.py 兜底先 ALTER 过的场景）
    if _COL_NAME not in existing_cols:
        op.add_column(
            "encounters",
            sa.Column(
                _COL_NAME,
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )

    # 加 GIN 索引方便按 HIS 患者编号反查
    # 用原生 SQL，因为 op.create_index 对 jsonb_path_ops 支持不一致
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS {_IDX_NAME}
        ON encounters
        USING GIN ((his_external_ref -> 'his_patient_no'))
    """)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_IDX_NAME}")
    op.drop_column("encounters", _COL_NAME)
