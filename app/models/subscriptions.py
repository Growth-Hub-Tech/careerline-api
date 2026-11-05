"""Subscriptions (Days 25-26).

- subscription_plans: what can be subscribed to (reference data from
  seeds/subscription_plans.json, filled by the seed loader). A plan taken out of the file is
  retired (is_active false): no longer sold, kept by the people already on it.
- subscriptions: one per paid plan of a person (learner_id pays). status active (paid period
  running), past_due (its renewal could not be charged; still usable for the grace days) or
  cancelled (ended). A person has at most one active or past_due subscription. An organisation
  plan names the organisation it gives seats to. authorization_code: Paystack's reusable card
  authorization from the first payment, used to charge renewals (Day 26).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

PLAN_AUDIENCES = ("individual", "recruiter", "organisation")
PLAN_INTERVALS = ("monthly", "yearly")
SUBSCRIPTION_STATUSES = ("active", "past_due", "cancelled")


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint(
            "audience IN ('individual', 'recruiter', 'organisation')",
            name="ck_subscription_plans_audience",
        ),
        CheckConstraint("interval IN ('monthly', 'yearly')", name="ck_subscription_plans_interval"),
    )

    plan_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    audience: Mapped[str] = mapped_column(String(20), nullable=False)
    interval: Mapped[str] = mapped_column(String(20), nullable=False)
    # in the smallest unit (kobo)
    price_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="NGN")
    credits_per_interval: Mapped[int] = mapped_column(Integer, nullable=False)
    seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'past_due', 'cancelled')", name="ck_subscriptions_status"
        ),
        Index("ix_subscriptions_learner", "learner_id", "created_at"),
        # at most one live subscription per person
        Index(
            "uq_subscriptions_one_live",
            "learner_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'past_due')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("subscription_plans.plan_id"), nullable=False
    )
    organisation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authorization_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
