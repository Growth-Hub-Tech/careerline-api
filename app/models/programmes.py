"""Programmes (Day 14): Incubate and partner courses that prepare for a job role, and the clicks
on them (for referral reporting).

Programmes, and which roles and skills each one covers, are reference data from
seeds/programmes.json. A programme taken out of the file is retired (is_active false), never
deleted, so old clicks keep pointing at it.
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
    String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Programme(Base):
    __tablename__ = "programmes"
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('incubate', 'partner')", name="ck_programmes_provider_type"
        ),
        CheckConstraint("mode IN ('online', 'in_person', 'hybrid')", name="ck_programmes_mode"),
        CheckConstraint("duration_weeks >= 1", name="ck_programmes_duration"),
        CheckConstraint("price_amount >= 0", name="ck_programmes_price"),
    )

    programme_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_weeks: Mapped[int] = mapped_column(Integer, nullable=False)
    # in the smallest unit (kobo for NGN), as Money
    price_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="NGN")
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProgrammeRole(Base):
    __tablename__ = "programme_roles"

    programme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("programmes.programme_id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_roles.role_id", ondelete="CASCADE"), primary_key=True
    )


class ProgrammeSkill(Base):
    __tablename__ = "programme_skills"

    programme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("programmes.programme_id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), primary_key=True)
    # the order the programme lists its skills in
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ProgrammeClick(Base):
    __tablename__ = "programme_clicks"
    __table_args__ = (
        Index("ix_programme_clicks_programme", "programme_id", "clicked_at"),
        Index("ix_programme_clicks_learner", "learner_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    click_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    programme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("programmes.programme_id"), nullable=False
    )
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    result_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("test_attempt.attempt_id", ondelete="SET NULL"), nullable=True
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
