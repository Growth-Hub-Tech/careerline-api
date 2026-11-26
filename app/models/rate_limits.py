"""The rate limiter's events (app/core/rate_limit.py)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class RateLimitEvent(Base):
    """One counted action (a failed login, a sign-up...). See app/core/rate_limit.py."""

    __tablename__ = "rate_limit_events"
    __table_args__ = (Index("ix_rate_limit_events_bucket_created_at", "bucket", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # "<kind>:<keyed hash of the email or IP>": never the email or IP itself
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
