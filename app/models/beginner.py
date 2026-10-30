"""The beginner path (Day 13): each intake a person submits, with their answers and the career
paths they were given at the time."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class BeginnerIntake(Base):
    __tablename__ = "beginner_intakes"
    __table_args__ = (Index("ix_beginner_intakes_learner", "learner_id", "submitted_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    # question id -> the option values picked
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # the career paths given, as answered (CareerPathRecommendation)
    recommendations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
