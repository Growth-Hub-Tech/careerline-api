"""Organisation audits (Days 21-24): the team roster, audits, targets.

- team_members: everyone the organisation tests, one per email per organisation (emails kept in
  lower case), each mapped to a job role. Their tests are team invitations (invitations.kind
  team_member, invitations.team_member_id). This is the organisation's own list: it is not an
  account and needs none.
- audits (Day 22): one round of testing for some roles. audit_members: who is in it, with the
  role they had then. Its invitations carry invitations.audit_id. Draft until started_at; the
  status (in_progress, completed) follows its invitations and is not stored.
- organisation_targets (Day 23): the level each role should reach in each skill, with an
  optional due date. Replaced as a whole by PUT /organisations/{id}/targets.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.models import LevelName, pg_enum


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("organisation_id", "email", name="uq_team_members_organisation_email"),
        Index("ix_team_members_organisation_name", "organisation_id", "full_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    department: Mapped[str | None] = mapped_column(String(80), nullable=True)
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_roles.role_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Audit(Base):
    __tablename__ = "audits"
    __table_args__ = (Index("ix_audits_organisation", "organisation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # the job roles it tests, in the order they were asked for
    role_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # None: a draft (no invitations sent yet)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditMember(Base):
    __tablename__ = "audit_members"

    audit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), primary_key=True
    )
    team_member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("team_members.id", ondelete="CASCADE"), primary_key=True
    )
    # the member's role when the audit was made (the roster may change later)
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_roles.role_id", ondelete="RESTRICT"), nullable=False
    )


class OrganisationTarget(Base):
    __tablename__ = "organisation_targets"

    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_roles.role_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), primary_key=True)
    target_level: Mapped[LevelName] = mapped_column(pg_enum(LevelName, "levelname"), nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
