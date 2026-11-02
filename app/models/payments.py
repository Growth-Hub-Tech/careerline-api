"""Payments and credits (Day 16).

- credit_packs: what credits cost (reference data from seeds/credit_packs.json).
- payments: one Paystack checkout each, pending -> paid | failed | abandoned. A payment's credits
  are added by exactly one credit transaction (credit_transactions.payment_id is unique).
- credit_balances: one row per person, locked while it changes, so the balance and the history
  always agree.
- credit_transactions: every change to a balance (purchase, test_started, refund,
  subscription_grant), with the balance after it.
- paystack_events: every webhook event once (event + Paystack's id), so a retried event is
  recognised and ignored.
- test_prices (Day 17): what a test costs in credits, per skill (seeds/test_prices.json); a
  skill not listed is free. A test's credits are taken once when it starts (credit transaction
  test_started with its attempt_id) and given back at most once (refund).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

PAYMENT_STATUSES = ("pending", "paid", "failed", "abandoned")
CREDIT_REASONS = ("purchase", "test_started", "refund", "subscription_grant")


class CreditPack(Base):
    __tablename__ = "credit_packs"
    __table_args__ = (
        CheckConstraint("credits > 0", name="ck_credit_packs_credits"),
        CheckConstraint("price_amount > 0", name="ck_credit_packs_price"),
    )

    pack_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    price_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # kobo
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="NGN")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'abandoned')", name="ck_payments_status"
        ),
        CheckConstraint(
            "item_type IN ('credit_pack', 'subscription_plan')", name="ck_payments_item_type"
        ),
        Index("ix_payments_learner", "learner_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # kobo
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)  # added once paid
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    authorization_url: Mapped[str] = mapped_column(String(500), nullable=False)
    access_code: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    callback_url: Mapped[str] = mapped_column(String(500), nullable=False)
    paystack_transaction_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Day 25: the subscription a paid subscription_plan payment started or renewed
    subscription_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CreditBalance(Base):
    __tablename__ = "credit_balances"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_credit_balances_balance"),)

    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('purchase', 'test_started', 'refund', 'subscription_grant')",
            name="ck_credit_transactions_reason",
        ),
        CheckConstraint("change <> 0", name="ck_credit_transactions_change"),
        Index("ix_credit_transactions_learner", "learner_id", "created_at"),
        UniqueConstraint("attempt_id", "reason", name="uq_credit_transactions_attempt_reason"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("learner.learner_id", ondelete="CASCADE"), nullable=False
    )
    change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # a purchase: the payment it came from (one transaction per payment, ever)
    payment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    # a test's charge or refund (Day 17): one of each per attempt, ever
    attempt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("test_attempt.attempt_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaystackEvent(Base):
    __tablename__ = "paystack_events"
    __table_args__ = (UniqueConstraint("event", "paystack_id", name="uq_paystack_events_event"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(80), nullable=False)
    # Paystack's id of the thing the event is about (data.id); the body's hash when it has none
    paystack_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TestPrice(Base):
    __tablename__ = "test_prices"
    __test__ = False  # not a pytest test class
    __table_args__ = (CheckConstraint("price_credits >= 0", name="ck_test_prices_price"),)

    skill_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skills.skill_id", ondelete="CASCADE"), primary_key=True
    )
    price_credits: Mapped[int] = mapped_column(Integer, nullable=False)
