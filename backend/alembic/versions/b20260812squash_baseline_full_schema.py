"""baseline_full_schema —— 压缩重置基线（2026-08-12 迁移四通道收口）

Revision ID: b20260812squash
Revises: None（新链起点）
Create Date: 2026-08-12

背景（收口前的四通道乱局）：
  历史上 schema 由四条通道并行维护：init_db/create_all、migrate.py 命令式
  ALTER、schema_compat.py 启动期 DDL、alembic 增量链。旧 alembic 链里没有
  任何建表语句（空库跑 upgrade 必挂），单一真源无从谈起。

本基线 = 压缩重置（squash）+ **冻结快照**：
  - 旧 12 条 revision 已删除，本文件是新链唯一起点
  - 全部表/索引 DDL 冻结在同目录 b20260812squash_schema.sql（2026-08-12 由
    当时的模型元数据按 PostgreSQL 方言编译生成，**此后不随模型演进**——
    模型再改必须写新 revision，CI 的 `alembic check` 门禁会对比模型与
    迁移链建出的库，漂移即红）
  - 快照之外手写补三样（模型声明不了）：pgcrypto 扩展、4 个身份字段
    CHECK 约束、audit_logs 只追加触发器
  - 历史上的一次性数据迁移（拼音回填 / profile JSONB 搬迁 / 脏数据清理）
    不进基线——生产早已执行完毕，全新库无数据可迁

为什么冻结而不用 create_all（2026-08-12 复检修复）：
  create_all 读的是"当前代码里最新的模型"，是随模型演进的活基线——全新库
  永远和模型一致，任何"模型 vs 库"的校验都变成同义反复，"改模型忘写迁移"
  会在 CI 全绿的情况下让存量生产库静默缺列。冻结后基线是历史事实，
  校验才有判别力。

存量库如何过渡：
  生产/旧库不执行本基线（表已存在）——由 alembic_guard.py 在列级校验通过后
  stamp 到本基线；库若缺列（如恢复了旧备份）guard 直接 FATAL 拒绝带病 stamp。
"""

from pathlib import Path
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
    # 1. pgcrypto：种子数据的 gen_random_uuid() 依赖
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # 2. 全量建表：执行冻结 DDL 快照（本基线只在空库上真正执行——存量库
    #    走 guard stamp——故无需 IF NOT EXISTS）
    sql_path = Path(__file__).with_name("b20260812squash_schema.sql")
    for statement in sql_path.read_text(encoding="utf-8").split(";\n\n"):
        statement = statement.strip().rstrip(";")
        if statement:
            op.execute(statement)

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
