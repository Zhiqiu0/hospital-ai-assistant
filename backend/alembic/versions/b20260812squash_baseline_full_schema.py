"""baseline_full_schema —— 压缩重置基线（2026-08-12 迁移四通道收口）

Revision ID: b20260812squash
Revises: None（新链起点）
Create Date: 2026-08-12

背景（收口前的四通道乱局）：
  历史上 schema 由四条通道并行维护：init_db/create_all、migrate.py 命令式
  ALTER、schema_compat.py 启动期 DDL、alembic 增量链。旧 alembic 链里没有
  任何建表语句（空库跑 upgrade 必挂），单一真源无从谈起。

本基线 = 压缩重置（squash）：
  - 旧 12 条 revision 已删除，本文件是新链唯一起点
  - 建表以 **模型元数据（Base.metadata）为唯一真源**：create_all 建出全部表、
    列、以及模型 __table_args__ 声明的全部索引/唯一约束（含 patients 部分
    唯一索引、encounters GIN 索引、病历热路径索引等）
  - 模型声明不了的三样手写补齐：pgcrypto 扩展、4 个身份字段 CHECK 约束、
    audit_logs 只追加触发器
  - 历史上的一次性数据迁移（拼音回填 / profile JSONB 搬迁 / 脏数据清理）
    不进基线——生产早已执行完毕，全新库无数据可迁

存量库如何过渡：
  生产/旧库不执行本基线（表已存在）——由 alembic_guard.py 检测到
  alembic_version 缺失或指向已删除的旧 revision 时，stamp 到本基线。

⚠️ 后续 revision 的铁律（写新迁移必读）：
  基线用 create_all，对全新库建出的是"当时最新模型"的表结构——这意味着
  后续每条 revision 都必须**幂等**（inspector 判断列/索引是否已存在再加），
  否则全新库上"基线已建出新列 + revision 再 add_column"会撞车。
  CI 的 tests_pg/test_alembic_single_source.py 空库门禁会拦住违规迁移。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b20260812squash"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 身份字段 CHECK 约束（生产已有，模型未声明——SQLite 测试库不支持同名语法，
# 故不放模型 __table_args__，由基线手写；幂等：已存在则跳过）
_CHECK_CONSTRAINTS = (
    ("patients", "ck_patient_id_card_length", "id_card IS NULL OR length(id_card) = 18"),
    ("patients", "ck_patient_phone_length", "phone IS NULL OR length(phone) = 11"),
    ("patients", "ck_patient_contact_phone_length", "contact_phone IS NULL OR length(contact_phone) = 11"),
    ("users", "ck_user_phone_length", "phone IS NULL OR length(phone) = 11"),
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. pgcrypto：种子数据的 gen_random_uuid() 依赖
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # 2. 全量建表：显式导入全部模型模块（与 alembic/env.py 同一清单），
    #    让 Base.metadata 完整后 create_all（checkfirst 幂等，存量库全跳过）
    from app.database import Base
    import app.models.user            # noqa: F401
    import app.models.patient         # noqa: F401
    import app.models.encounter       # noqa: F401
    import app.models.medical_record  # noqa: F401
    import app.models.audit_log       # noqa: F401
    import app.models.config          # noqa: F401
    import app.models.voice_record    # noqa: F401
    import app.models.imaging         # noqa: F401
    import app.models.lab_report      # noqa: F401
    import app.models.revoked_token   # noqa: F401
    import app.models.inpatient       # noqa: F401
    import app.models.ai_feedback     # noqa: F401

    Base.metadata.create_all(bind=bind, checkfirst=True)

    # 3. 身份字段 CHECK 约束（幂等：查 pg_constraint 再加）
    for table, name, expr in _CHECK_CONSTRAINTS:
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
                    ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr});
                END IF;
            END $$;
        """)

    # 4. audit_logs 只追加触发器（2026-08-11 病历可信：审计不可改删）
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs 是只追加表，禁止 % 操作', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs")
    op.execute("""
        CREATE TRIGGER trg_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only();
    """)


def downgrade() -> None:
    # 基线不支持回退——回退等于删库。存量库恢复走迁移前 pg_dump 备份。
    raise NotImplementedError("基线 revision 不支持 downgrade，恢复请用迁移前备份")
