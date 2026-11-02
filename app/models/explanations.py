"""Explanations of test questions (Day 11): asked from the AI once per question and kept for
everyone. question_digest is a fingerprint of the question, its options and its right answer
when the explanation was made: if the question changes, the kept one no longer counts."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class QuestionExplanation(Base):
    __tablename__ = "question_explanations"

    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.question_id", ondelete="CASCADE"), primary_key=True
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    question_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
