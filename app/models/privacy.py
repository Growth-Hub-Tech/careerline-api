"""Privacy (Day 18, NDPR / GDPR).

- learner_consents: each person's current answer per consent key; consent_events: every change,
  with its time (the record that consent was given or withdrawn).
- data_exports: a copy of everything held about a person, made by a background job, kept
  DATA_EXPORT_DAYS and then emptied.
- account_deletions: one per person: scheduled (cancellable for ACCOUNT_DELETION_GRACE_DAYS),
  cancelled or completed (the person's data is erased; the row stays as the record).
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

# Day 31: AuxHR and Incubate sharing are off until the person turns them on, like the others
CONSENT_KEYS = (
    "marketing_emails",
    "share_profile_with_recruiters",
    "product_research",
    "aux_hr_sharing",
    "incubate_sharing",
)


class LearnerConsent(Base):
    __tablename__ = "learner_consents"

    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConsentEvent(Base):
    __tablename__ = "consent_events"
    __table_args__ = (Index("ix_consent_events_learner", "learner_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DataExport(Base):
    __tablename__ = "data_exports"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'ready', 'failed')", name="ck_data_exports_status"),
        Index("ix_data_exports_learner", "learner_id", "requested_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # the JSON file; emptied once the export expires
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class AccountDeletion(Base):
    __tablename__ = "account_deletions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed')",
            name="ck_account_deletions_status",
        ),
    )

    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
