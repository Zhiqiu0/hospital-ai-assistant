"""record_versions 补 (medical_record_id, version_no) 唯一约束

Revision ID: h20260814veruniq
Revises: g20260814audittrunc
Create Date: 2026-08-14

为什么需要（2026-08-13 第五轮审计发现）：
  病历版本号是「读 current_version + 1」算出来的，而 record_versions 上只有普通
  索引、没有唯一约束。并发写入会产生两条 version_no 相同的版本，此后按
  `RecordVersion.version_no == MedicalRecord.current_version` 取正文的 JOIN 会
  命中 2 行——**同一份病历刷新两次可能看到不同内容**，医疗场景不可接受。

  应用层已经在 save_content / quick_save / revise_record 三处都加了
  with_for_update 行锁（revise 那处是本轮补的）。但行锁只在同一个数据库实例内
  按事务串行化，且依赖每条写路径都记得加——数据库层的唯一约束是最后一道
  兜底，任何路径漏掉都会当场失败而不是静默产出重复版本。

存量清理：先合并可能已存在的重复（保留 created_at 最早的那条，其余顺延到
新的版本号末尾），再建约束。演练库与生产实测均无重复，此处只是防御性处理。

幂等：先判约束是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h20260814veruniq"
down_revision: Union[str, None] = "g20260814audittrunc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "uq_record_versions_record_version"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "record_versions" not in inspector.get_table_names():
        return
    existing = {u["name"] for u in inspector.get_unique_constraints("record_versions")}
    if CONSTRAINT in existing:
        return

    # 存量重复顺延：同 (medical_record_id, version_no) 保留最早那条，
    # 其余改成该病历现有最大版本号之后的空位，避免建约束时失败。
    op.execute("""
        WITH dup AS (
            SELECT id, medical_record_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY medical_record_id, version_no
                       ORDER BY created_at, id
                   ) AS rn
            FROM record_versions
        ),
        maxv AS (
            SELECT medical_record_id, MAX(version_no) AS mx
            FROM record_versions GROUP BY medical_record_id
        )
        UPDATE record_versions rv
        SET version_no = maxv.mx + dup.rn - 1
        FROM dup, maxv
        WHERE rv.id = dup.id
          AND dup.rn > 1
          AND maxv.medical_record_id = dup.medical_record_id
    """)

    op.create_unique_constraint(
        CONSTRAINT, "record_versions", ["medical_record_id", "version_no"]
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "record_versions", type_="unique")
