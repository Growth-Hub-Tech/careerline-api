"""Organisation audits (Days 21-24): the team roster, audits, targets.

- team_members: everyone the organisation tests, one per email per organisation (emails kept in
  lower case), each mapped to a job role. Their tests are team invitations (invitations.kind
  team_member, invitations.team_member_id). This is the organisation's own list: it is not an
  account and needs none.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


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
