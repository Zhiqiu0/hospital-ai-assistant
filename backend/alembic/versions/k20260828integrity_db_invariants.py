# -*- coding: utf-8 -*-
"""DB 完整性兜底（2026-08-28 全量体检·数据完整性维度）

Revision ID: k20260828integrity
Revises: s20260822pydigit
Create Date: 2026-08-28

为什么：审计确认多条业务不变量只有"应用层记得加锁/校验"一层保护，
DB 零 CHECK、关键唯一键缺失。本迁移补最后防线：

1. medical_records (encounter_id, record_type, record_no) 唯一
   ——文书身份键 = HIS 回写幂等键，重复即互相覆盖。先按 h20260814veruniq
   同款顺延法清理存量重复，再建唯一索引。
2. 枚举 CHECK（NOT VALID：只管新写入，存量不校验故绝不因脏历史行炸部署）：
   medical_records.status / record_type、encounters.status / visit_type。
3. diagnoses 主诊断唯一部分索引（防未来新增写路径漏加接诊行锁）。
4. diagnosis_codes (code_type, code) 唯一（构建脚本已去重，存量兜底清理）。

（users.employee_no 唯一改为应用层修复——生产可能存在历史重复工号，
 DB 约束会造成模型/库不对拍，_map_doctor 兜底查询已改为多行命中报错）

幂等：索引 IF NOT EXISTS；约束先查 pg_constraint 再加；SQLite 测试库跳过。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k20260828integrity"
down_revision: Union[str, None] = "s20260822pydigit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RECORD_TYPES = ("outpatient", "emergency", "admission_note", "first_course_record",
                 "course_record", "senior_round", "discharge_record",
                 "pre_op_summary", "op_record", "post_op_record")


def _add_check(bind, table: str, name: str, expr: str) -> None:
    """幂等加 NOT VALID CHECK：已存在跳过；NOT VALID 不校验存量行。"""
    exists = bind.execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).scalar()
    if not exists:
        bind.execute(sa.text(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID"))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite 测试库：应用层校验已覆盖，DB 兜底仅生产 PG

    # ── 1. 文书三元组唯一 ────────────────────────────────────────────
    # 存量重复顺延：同 (enc,type,no) 的行按 created_at 保最早，其余 record_no
    # 依次抬到该 (enc,type) 当前最大值之后（与 h20260814veruniq 同哲学）
    bind.execute(sa.text("""
        WITH d AS (
            SELECT id, encounter_id, record_type, record_no,
                   ROW_NUMBER() OVER (
                       PARTITION BY encounter_id, record_type, record_no
                       ORDER BY created_at, id) AS rn
            FROM medical_records
        ), m AS (
            SELECT encounter_id, record_type, MAX(record_no) AS mx
            FROM medical_records GROUP BY encounter_id, record_type
        )
        UPDATE medical_records r
        SET record_no = m.mx + d.rn - 1
        FROM d JOIN m ON m.encounter_id = d.encounter_id
                     AND m.record_type = d.record_type
        WHERE r.id = d.id AND d.rn > 1
    """))
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_medrec_enc_type_no "
        "ON medical_records (encounter_id, record_type, record_no)"))

    # ── 2. 枚举 CHECK（NOT VALID）────────────────────────────────────
    rt = ", ".join(f"'{t}'" for t in _RECORD_TYPES)
    _add_check(bind, "medical_records", "ck_medrec_status",
               "status IN ('draft', 'editing', 'submitted')")
    _add_check(bind, "medical_records", "ck_medrec_record_type",
               f"record_type IN ({rt})")
    _add_check(bind, "encounters", "ck_enc_status",
               "status IN ('in_progress', 'completed', 'cancelled')")
    _add_check(bind, "encounters", "ck_enc_visit_type",
               "visit_type IN ('outpatient', 'emergency', 'inpatient')")

    # ── 4. 主诊断唯一部分索引（存量多主先保排序最前，其余取消主标）────
    bind.execute(sa.text("""
        WITH d AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY encounter_id ORDER BY sort_order, id) AS rn
            FROM diagnoses WHERE is_primary
        )
        UPDATE diagnoses SET is_primary = FALSE
        WHERE id IN (SELECT id FROM d WHERE rn > 1)
    """))
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_diag_primary_per_enc "
        "ON diagnoses (encounter_id) WHERE is_primary"))

    # ── 5. 字典 (code_type, code) 唯一（存量重复保最小 id）────────────
    bind.execute(sa.text("""
        DELETE FROM diagnosis_codes a USING diagnosis_codes b
        WHERE a.code_type = b.code_type AND a.code = b.code AND a.id > b.id
    """))
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_diagcode_type_code "
        "ON diagnosis_codes (code_type, code)"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for idx in ("uq_medrec_enc_type_no",
                "uq_diag_primary_per_enc", "uq_diagcode_type_code"):
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {idx}"))
    for tbl, name in (("medical_records", "ck_medrec_status"),
                      ("medical_records", "ck_medrec_record_type"),
                      ("encounters", "ck_enc_status"),
                      ("encounters", "ck_enc_visit_type")):
        bind.execute(sa.text(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {name}"))
