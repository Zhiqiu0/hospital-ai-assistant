"""doctor_codes 表 + users.must_change_password（批量开户）

Revision ID: d20260813codes
Revises: c20260812adoptidx
Create Date: 2026-08-13

变更内容：
  1. 新建 doctor_codes 表（users 1:N）：一位医生可挂多个 HIS 工号。
     安吉濮氏医院真实名单证实同一医生因「门诊/住院」「本人/助理」被分配了
     多个工号（汪来煜 6069/16029/16039），原先 User.employee_no 只能存一个，
     HIS 推另一个工号即映射失败（ack 40007，接诊进不来）。
  2. users 加 must_change_password：批量开户用统一初始密码便于分发，
     未改密前只放行改密端点，避免"知道工号就能用初始密码登进别人账号"。
  3. 存量 users.employee_no 回填进 doctor_codes（保持既有映射不断）。

幂等：建表/加列/回填均先判存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d20260813codes"
down_revision: Union[str, None] = "c20260812adoptidx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. doctor_codes 表
    if "doctor_codes" not in inspector.get_table_names():
        op.create_table(
            "doctor_codes",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("note", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )
        # 模型写的是 code(unique=True, index=True)，SQLAlchemy 把这两个合并渲染成
        # 「一条唯一索引」而非「唯一约束 + 普通索引」。这里必须照抄它的渲染方式，
        # 否则 CI 的 alembic check 会判定 schema 漂移。
        op.create_index("ix_doctor_codes_code", "doctor_codes", ["code"], unique=True)

    # 2. users.must_change_password
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "must_change_password" not in user_cols:
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
        )

    # 3. 存量 employee_no 回填（只补缺，重复执行不会插重复）
    op.execute("""
        INSERT INTO doctor_codes (id, user_id, code, note, created_at, updated_at)
        SELECT gen_random_uuid()::text, u.id, u.employee_no, '存量回填', NOW(), NOW()
        FROM users u
        WHERE u.employee_no IS NOT NULL
          AND u.employee_no <> ''
          AND NOT EXISTS (SELECT 1 FROM doctor_codes d WHERE d.code = u.employee_no)
    """)


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
    op.drop_index("ix_doctor_codes_code", table_name="doctor_codes")
    op.drop_table("doctor_codes")
