"""A person's skill history (Day 10): one entry per finished test, saved in the same
transaction as the result."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.models import LevelName, pg_enum


class SkillHistory(Base):
    __tablename__ = "skill_history"
    __table_args__ = (
        Index("ix_skill_history_learner_skill", "learner_id", "skill_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.skill_id"), nullable=False)
    attempt_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("test_attempt.attempt_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    level: Mapped[LevelName] = mapped_column(pg_enum(LevelName, "levelname"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    # subskill ids
    strengths: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'")
    )
    weaknesses: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
