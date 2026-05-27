"""patient_id_card_unique

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-27 12:00:00.000000

变更内容：
  patients 表的 id_card 加 partial unique index：
    UNIQUE (id_card) WHERE id_card IS NOT NULL AND is_deleted = false

为什么要 partial：
  - id_card 是可选字段（无证患者/婴儿）→ NULL 必须允许多条，不能整列 UNIQUE
  - 软删患者保留历史 → is_deleted=true 不参与唯一约束
  - 同一身份证只允许一份活跃档案

为什么应用层有 quick-start 查重还要 DB 层 UNIQUE：
  - quick-start 内部 find_existing → create 之间存在 race window
  - 并发请求/双击/直接 POST /patients 绕过 quick-start 都可能造脏数据
  - DB 层兜底是"宽 App + 严 DB"中的严 DB 一半，物理防线

兼容历史脏数据（upgrade 自带清理）：
  - 如果已存在重复 id_card（多份活跃档案），保留 created_at 最早的一条
  - 其他都软删（is_deleted=true + deleted_at=now() + deleted_by=NULL 表示系统迁移操作）
  - 这样建索引不会因约束失败，且历史档案仍可在管理后台按 ID 找到
  - 生产数据正常情况无重复（quick-start 已防），主要兜底本地/早期遗留场景
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_patients_id_card_active"


def upgrade() -> None:
    bind = op.get_bind()

    # 1. 清理历史重复（保留 created_at 最早，其余软删）
    # 用 CTE 找出每组重复里的"幸存者"，其他全部软删
    # is_from_his / phone / address 等字段保持不动，只动 is_deleted/deleted_at
    bind.execute(sa.text("""
        WITH dups AS (
            SELECT id, id_card,
                   ROW_NUMBER() OVER (
                       PARTITION BY id_card
                       ORDER BY created_at ASC, id ASC
                   ) AS rn
            FROM patients
            WHERE id_card IS NOT NULL
              AND is_deleted = false
        )
        UPDATE patients
        SET is_deleted = true,
            deleted_at = NOW()
        WHERE id IN (
            SELECT id FROM dups WHERE rn > 1
        )
    """))

    # 2. 建 partial unique index
    # 用原生 SQL，因为 SQLAlchemy 的 op.create_index(..., postgresql_where=...) 在不同
    # 版本表现不一致；这里直接 DDL 最稳。
    op.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME}
        ON patients (id_card)
        WHERE id_card IS NOT NULL AND is_deleted = false
    """)


def downgrade() -> None:
    # 仅删索引；历史清理操作不可逆（被软删的患者不自动恢复，需 DBA 手工）
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
