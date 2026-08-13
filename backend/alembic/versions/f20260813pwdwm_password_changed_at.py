"""users.password_changed_at（密码水印，改密/重置后踢掉已签发会话）

Revision ID: f20260813pwdwm
Revises: e20260813qcdrift
Create Date: 2026-08-13

为什么需要（2026-08-13 第三轮审计发现）：
  改密与管理员重置密码都**不吊销已签发的 JWT**，而本项目 token 有效期是 30 天。
  这让「账号疑似泄露 → 信息科重置密码」这个标准处置动作根本踢不掉攻击者手里
  已有的会话——重置等于白做。配合本轮上线的「全院统一初始密码」，暴露面更实：
  谁抢在医生之前用初始密码登进去拿到 token，之后无论医生怎么改密码，
  那个 token 都还能用满 30 天。

做法：记录密码最后修改时间作为水印，get_current_user 拒绝签发时刻（JWT 的 iat）
早于水印的 token。新签发的 token 都带 iat；本次改动之前签发的老 token 没有 iat，
在水印非空时一并判失效（只影响改过密的账号，代价是重登一次）。

时区口径：与全项目一致存 naive 本地时间（生产容器 TZ=Asia/Shanghai），
比对时把 iat 也转成 naive 本地时间，两边同一口径——若按 UTC 解读会凭空差 8 小时，
后果是全院 token 一起失效。

默认 NULL：存量账号水印为空即不做比对，现有会话不受影响，不会因为这次升级
把全院医生踢下线。

幂等：先判列是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f20260813pwdwm"
down_revision: Union[str, None] = "e20260813qcdrift"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "password_changed_at" not in cols:
        op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
