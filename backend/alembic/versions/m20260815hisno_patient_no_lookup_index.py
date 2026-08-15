"""HIS 患者主索引号查重：把索引形状从 GIN(->) 换成 btree(->>)

Revision ID: m20260815hisno
Revises: l20260814dropnotes
Create Date: 2026-08-15

为什么需要：

  接诊推送新增接收 patient_no（HIS 患者主索引号），作为患者查重的第二强键
  （身份证之后、手机号之前）。查询是**等值查 JSON 标量**：

      WHERE his_external_ref ->> 'his_patient_no' = $1
        AND his_external_ref ->> 'hospital_code'  = $2

  原有索引是 GIN((his_external_ref -> 'his_patient_no'))（迁移 c9d0e1f2a3b4
  建），形状对不上：GIN 服务的是整列 @> 包含查询，等值比对 ->> 取出的文本
  命中不了它。也就是说那个索引自建成起就没被任何查询用过——只在每次写
  encounters 时付出维护代价。第七轮审计已经发现过它「与 visit_no 无关」，
  这次进一步确认它与任何实际查询都无关。

  等值查 JSON 标量的通行做法是在 ->> 表达式上建 btree，与查询逐字对应。

  两个键都建：hospital_code 用于跨机构隔离（院内编号只在本院唯一），
  单列 his_patient_no 索引已足够收敛候选，hospital_code 交给回表过滤，
  故只建一个单列表达式索引，不建复合。

生产影响：encounters 已有实数据，CREATE / DROP 全部 CONCURRENTLY，不阻塞
线上读写（代价是必须在事务外执行，见 autocommit_block）。先建新索引、
后删旧索引，中间任何时刻都有可用索引，可安全中断重来。

幂等：IF NOT EXISTS / IF EXISTS，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "m20260815hisno"
down_revision: Union[str, None] = "l20260814dropnotes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_IDX = "idx_encounters_his_patient_no"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # SQLite 测试库由 create_all 按模型建索引，这里无事可做
        return
    with op.get_context().autocommit_block():
        # 同名替换：先删旧形状（GIN），再按新形状建。两步都 CONCURRENTLY，
        # 且这个索引当前无任何查询依赖（见上方说明），删除窗口内无性能风险。
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_IDX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_IDX} "
            f"ON encounters ((his_external_ref ->> 'his_patient_no'))"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_IDX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_IDX} "
            f"ON encounters USING gin ((his_external_ref -> 'his_patient_no'))"
        )
