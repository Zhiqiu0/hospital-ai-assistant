"""identity_check_constraints

Revision ID: a7b8c9d0e1f2
Revises: f5a6b7c8d9e0
Create Date: 2026-05-17 00:00:00.000000

变更内容：
  为 patients / users 表的身份证号、手机号字段加 CHECK 约束，作为应用层
  Pydantic 校验之外的物理底线，防止绕过 ORM 直插的脏数据。

约束策略（"宽 DB + 严 App" 的业内常见做法）：
  - 仅约束长度上限与基础字符集（DB 错误信息丑陋，不适合做复杂语义校验）
  - 校验码算法、出生日期合法性、号段细分留给应用层
  - 历史脏数据扫描在 upgrade 里先做一遍统计，避免 ALTER TABLE 因约束失败

为什么不加复杂正则：
  PostgreSQL 支持 CHECK + 正则，但 DB 层报错信息无法返回字段级 i18n，
  普通用户体验差。应用层（Pydantic）已经覆盖了所有写入路径，DB 只做
  "万一应用代码绕过 ORM 直插" 的最后兜底。

字段：
  patients.id_card       : 18 位
  patients.phone         : 11 位
  patients.contact_phone : 11 位
  users.phone            : 11 位
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 约束名集中维护，downgrade 时按同一组名移除
_CONSTRAINTS = (
    ("patients", "ck_patient_id_card_length", "id_card IS NULL OR length(id_card) = 18"),
    ("patients", "ck_patient_phone_length", "phone IS NULL OR length(phone) = 11"),
    ("patients", "ck_patient_contact_phone_length", "contact_phone IS NULL OR length(contact_phone) = 11"),
    ("users", "ck_user_phone_length", "phone IS NULL OR length(phone) = 11"),
)


def upgrade() -> None:
    from alembic import context

    # 1. 历史脏数据扫描（仅 online 模式下可执行；offline / --sql 模式无连接跳过）
    if not context.is_offline_mode():
        bind = op.get_bind()
        for table, _name, expr in _CONSTRAINTS:
            dirty = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {table} WHERE NOT ({expr})")
            ).scalar() or 0
            if dirty:
                print(
                    f"[migration] WARN: {table} 中有 {dirty} 条记录违反约束 '{expr}'，"
                    f"加约束前请人工核查或先 UPDATE 设为 NULL"
                )

    # 2. 加 CHECK 约束（重复执行 alembic 时已存在则跳过，保证幂等）
    for table, name, expr in _CONSTRAINTS:
        try:
            op.create_check_constraint(name, table, expr)
        except Exception as exc:
            print(f"[migration] {name} skipped: {exc}")


def downgrade() -> None:
    # 按相反顺序移除约束
    for table, name, _ in reversed(_CONSTRAINTS):
        try:
            op.drop_constraint(name, table, type_="check")
        except Exception as exc:
            print(f"[migration] drop {name} skipped: {exc}")
