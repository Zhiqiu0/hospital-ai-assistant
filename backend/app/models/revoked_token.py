from datetime import datetime, timezone
from sqlalchemy import DateTime, String
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
