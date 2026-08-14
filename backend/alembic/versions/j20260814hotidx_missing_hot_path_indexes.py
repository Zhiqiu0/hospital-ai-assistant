"""补齐四张表缺失的热路径索引（第七轮审计）

Revision ID: j20260814hotidx
Revises: i20260814recordno
Create Date: 2026-08-14

为什么需要（2026-08-14 第七轮审计发现）：

  audit_logs / ai_tasks / qc_issues / voice_records 四张表**一个索引都没有**，
  encounters 上还缺两个关键列的索引。逐条说明：

  1. encounters.visit_no —— HIS 接诊幂等查重每收到一条推送都要按它反查，
     且这条查询跑在 pg_advisory_xact_lock 里面。admit_service 里的注释一直
     宣称「生产 PG 用 GIN 索引命中 visit_no 后候选很少」，但那个 GIN 索引
     建的是 his_external_ref->'his_patient_no'，跟 visit_no 是两回事。
     实际每次患者叫号都全表扫 encounters，而且串行化在锁内。

  2. encounters.patient_id —— 档案页、既往接诊、病历列表全按它过滤。

  3. audit_logs —— 全库写入最频繁的表（每次 PHI 查阅落一行），管理端列表
     固定 ORDER BY created_at DESC 分页，无索引时每翻一页全表排序。
     患者档案读权限放开后审计是唯一的追责手段，这张表必须一直可用。

  4. ai_tasks —— 工作台恢复快照按 (encounter_id, task_type) 取最近一条，
     医生每开一个患者都要跑几次。

  5. qc_issues / voice_records —— 外键列在 PG 不会自动建索引，删父行时的
     外键检查要扫子表；voice_records 管理端还按 created_at 倒序分页。

生产影响：本项目生产是 2 核小机器且这几张表已有实数据，因此全部用
CREATE INDEX CONCURRENTLY，不阻塞线上读写（代价是必须在事务外执行，
见下方 autocommit_block）。

幂等：全部 IF NOT EXISTS，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "j20260814hotidx"
down_revision: Union[str, None] = "i20260814recordno"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (索引名, 表名, 列定义)
_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("idx_encounters_visit_no", "encounters", "visit_no"),
    ("idx_encounters_patient", "encounters", "patient_id"),
    ("idx_audit_logs_created", "audit_logs", "created_at"),
    ("idx_audit_logs_action_created", "audit_logs", "action, created_at"),
    ("idx_ai_tasks_enc_type_created", "ai_tasks", "encounter_id, task_type, created_at"),
    ("idx_qc_issues_task", "qc_issues", "ai_task_id"),
    ("idx_qc_issues_record", "qc_issues", "medical_record_id"),
    ("idx_voice_records_doctor_created", "voice_records", "doctor_id, created_at"),
    ("idx_voice_records_encounter", "voice_records", "encounter_id"),
)

# 部分索引单列（带 WHERE，与上面的普通索引建法不同）
_PARTIAL_INDEXES: tuple[tuple[str, str, str, str], ...] = (
    # latest_chain_hash 取「全局链尾」作为新签发的 prev_hash，**每次医生签发
    # 病历都要跑一次**：ORDER BY created_at DESC LIMIT 1 WHERE sign_hash IS NOT NULL。
    # record_versions 上原有的两个索引都不覆盖这个条件（adoption 那个是
    # source='doctor_signed' AND ai_similarity IS NOT NULL 的部分索引），
    # 于是签发热路径一直在全表扫 + 排序。绝大多数版本是草稿、没有 sign_hash，
    # 所以部分索引只覆盖签发版本，体积极小且精准。
    (
        "idx_record_versions_chain_tail",
        "record_versions",
        "created_at DESC",
        "sign_hash IS NOT NULL",
    ),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # SQLite 测试库由 create_all 按模型建索引，这里无事可做
        return
    # CONCURRENTLY 不能在事务里跑，必须切到 autocommit
    with op.get_context().autocommit_block():
        for name, table, cols in _INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({cols})"
            )
        for name, table, cols, where in _PARTIAL_INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} ({cols}) WHERE {where}"
            )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        for name, *_ in (*_INDEXES, *_PARTIAL_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
