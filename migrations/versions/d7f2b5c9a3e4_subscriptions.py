"""Subscriptions (Day 25)

subscription_plans: the plans on sale (reference data from seeds/subscription_plans.json, filled by
the seed loader).
subscriptions: each person's paid plan (active, past_due or cancelled; at most one active or
past_due per person), with the organisation an organisation plan gives seats to, and the
Paystack card authorization renewals are charged to (Day 26).
payments.subscription_id: the subscription a paid plan payment started or renewed.

On the test database: two new tables (the plans are loaded by the seed loader).

Revision ID: d7f2b5c9a3e4
Revises: c6e1a4b8f3d2
Create Date: 2026-11-02 21:35:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7f2b5c9a3e4"
down_revision: Union[str, Sequence[str], None] = "c6e1a4b8f3d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subscription_plans",
        sa.Column("plan_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("audience", sa.String(length=20), nullable=False),
        sa.Column("interval", sa.String(length=20), nullable=False),
        sa.Column("price_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="NGN", nullable=False),
        sa.Column("credits_per_interval", sa.Integer(), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=True),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.CheckConstraint(
            "audience IN ('individual', 'recruiter', 'organisation')",
            name="ck_subscription_plans_audience",
        ),
        sa.CheckConstraint(
            "interval IN ('monthly', 'yearly')", name="ck_subscription_plans_interval"
        ),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("seats", sa.Integer(), nullable=True),
        sa.Column("authorization_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'cancelled')", name="ck_subscriptions_status"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.plan_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_subscriptions_learner", "subscriptions", ["learner_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_subscriptions_one_live",
        "subscriptions",
        ["learner_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'past_due')"),
    )
    op.add_column("payments", sa.Column("subscription_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "payments_subscription_id_fkey",
        "payments",
        "subscriptions",
        ["subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("payments_subscription_id_fkey", "payments", type_="foreignkey")
    op.drop_column("payments", "subscription_id")
    op.drop_index(
        "uq_subscriptions_one_live",
        table_name="subscriptions",
        postgresql_where=sa.text("status IN ('active', 'past_due')"),
    )
    op.drop_index("ix_subscriptions_learner", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("subscription_plans")
