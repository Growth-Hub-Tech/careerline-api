"""Payments and credits (Day 16)

credit_packs: what credits cost (reference data from seeds/credit_packs.json).
payments: one Paystack checkout each (pending, paid, failed, abandoned).
credit_balances, credit_transactions: each person's credits and every change to them.
paystack_events: every Paystack webhook event once, so retries are ignored.

On the test database: five new tables (credit_packs filled by the seed loader); nothing else
changes.

Revision ID: b6d2e9f4a1c7
Revises: a3f5c8e1d7b2
Create Date: 2026-11-02 19:49:44.112563

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b6d2e9f4a1c7"
down_revision: Union[str, Sequence[str], None] = "a3f5c8e1d7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "credit_packs",
        sa.Column("pack_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("price_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="NGN", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint("credits > 0", name="ck_credit_packs_credits"),
        sa.CheckConstraint("price_amount > 0", name="ck_credit_packs_price"),
        sa.PrimaryKeyConstraint("pack_id"),
    )
    op.create_table(
        "paystack_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event", sa.String(length=80), nullable=False),
        sa.Column("paystack_id", sa.String(length=128), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event", "paystack_id", name="uq_paystack_events_event"),
    )
    op.create_table(
        "credit_balances",
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("balance", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("balance >= 0", name="ck_credit_balances_balance"),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("learner_id"),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("authorization_url", sa.String(length=500), nullable=False),
        sa.Column("access_code", sa.String(length=100), server_default="", nullable=False),
        sa.Column("callback_url", sa.String(length=500), nullable=False),
        sa.Column("paystack_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("channel", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "item_type IN ('credit_pack', 'subscription_plan')", name="ck_payments_item_type"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'abandoned')", name="ck_payments_status"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_payments_learner", "payments", ["learner_id", "created_at"], unique=False)
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("change", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('purchase', 'test_started', 'refund', 'subscription_grant')",
            name="ck_credit_transactions_reason",
        ),
        sa.CheckConstraint("change <> 0", name="ck_credit_transactions_change"),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
    )
    op.create_index(
        "ix_credit_transactions_learner",
        "credit_transactions",
        ["learner_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_credit_transactions_learner", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_index("ix_payments_learner", table_name="payments")
    op.drop_table("payments")
    op.drop_table("credit_balances")
    op.drop_table("paystack_events")
    op.drop_table("credit_packs")
