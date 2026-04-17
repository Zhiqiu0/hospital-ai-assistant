"""
已吊销 JWT 令牌表（models/revoked_token.py）

数据表：
  revoked_tokens : 存储已注销的 JWT jti（JWT ID），用于实现"登出后立即失效"

工作原理：
  JWT 本身是无状态的，普通做法是等 token 过期（默认 24 小时）。
  医疗系统要求登出后立即失效，因此采用"黑名单"机制：
    1. 用户登出时，把 token 的 jti 写入此表
    2. 每次请求时，get_current_user 检查 jti 是否在黑名单中
    3. 在黑名单中 → 拒绝请求，返回 401

清理策略：
  expires_at 字段记录令牌原始过期时间，可以定期清理已过期的黑名单记录：
    DELETE FROM revoked_tokens WHERE expires_at < NOW()
  已过期的 token 即使不在黑名单中也无法使用（JWT 本身 exp 验证会拒绝），
  所以过期后的黑名单记录可以安全删除。
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    """返回当前 UTC 时间（不带时区信息，与数据库 TIMESTAMP WITHOUT TIME ZONE 兼容）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RevokedToken(Base):
    """已吊销 JWT 令牌黑名单表。

    以 jti（JWT ID，每个 token 唯一）为主键，查询 O(1)。
    """

    __tablename__ = "revoked_tokens"

    # jti 是 JWT payload 中的唯一标识符，由 create_access_token 生成（UUID4）
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 原始 token 的过期时间，用于定期清理过期黑名单记录
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # token 被吊销（登出）的时间
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
