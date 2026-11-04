"""Recruiting (Days 19-20): an organisation's candidates and the invitations it sends.

- candidates: one per email per organisation (emails kept in lower case).
- invitations: a link (token) to take one catalogue test. sent -> accepted (the invitee signs
  in, accepts and gets an attempt) -> completed (that test finished); or revoked. An invitation
  still "sent" after expires_at shows as expired. The token is shown to the sender (their list
  carries invite_url), so it is stored as it is.
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("organisation_id", "email", name="uq_candidates_organisation_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("job_roles.role_id", ondelete="SET NULL"), nullable=True
    )
    added_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('sent', 'accepted', 'completed', 'revoked')", name="ck_invitations_status"
        ),
        CheckConstraint("kind IN ('candidate', 'team_member')", name="ck_invitations_kind"),
        Index("ix_invitations_organisation", "organisation_id", "sent_at"),
        Index("ix_invitations_candidate", "candidate_id"),
        Index("ix_invitations_team_member", "team_member_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    candidate_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    # kind team_member: the roster entry it tests (Day 21)
    team_member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("team_members.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="sent")
    sent_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="SET NULL"), nullable=True
    )
    attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("test_attempt.attempt_id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
