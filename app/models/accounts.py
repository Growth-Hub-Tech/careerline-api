"""Sign-in sessions."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AuthSession(Base):
    """One signed-in device. The token names it (sid); revoking it ends that token at once."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_learner_id", "learner_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # logout, logout_everywhere, password_reset, password_changed
    revoked_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
