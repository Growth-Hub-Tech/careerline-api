"""Job roles, the skills each needs, and the job-title ladder (Day 8).

All three are reference data from the seed files (seeds/job_roles.json, seeds/job_titles.json).
A role skill's target_level is what the role needs at the mid title; the ladder says how the
expected level moves for the other titles (app/services/roles_service.py).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.models import LevelName, pg_enum

TRACKS = ("tech", "revenue")


class JobRole(Base):
    __tablename__ = "job_roles"
    __table_args__ = (CheckConstraint("track IN ('tech', 'revenue')", name="ck_job_roles_track"),)

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    track: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_pilot: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobRoleSkill(Base):
    __tablename__ = "job_role_skills"

    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_roles.role_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), primary_key=True)
    target_level: Mapped[LevelName] = mapped_column(pg_enum(LevelName, "levelname"), nullable=False)
    # 1 = the role's main skill; the order the website lists them in
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class JobTitle(Base):
    __tablename__ = "job_titles"

    title_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    expected_level: Mapped[LevelName] = mapped_column(
        pg_enum(LevelName, "levelname"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
