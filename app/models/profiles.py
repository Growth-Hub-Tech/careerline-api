"""The person's profile (Day 28): what they tell us about themselves, one row per person, made on
their first PATCH /profile. Who may see it (visibility) is not stored here: it is their
share_profile_with_recruiters consent (app/models/privacy.py).

(learner_profile, in app/models/models.py, is something else: the answers to the behavioural
questions of a test.)
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class PersonProfile(Base):
    __tablename__ = "profiles"

    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), primary_key=True
    )
    headline: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    years_experience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    goals: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    weekly_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget: Mapped[str | None] = mapped_column(String(20), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
