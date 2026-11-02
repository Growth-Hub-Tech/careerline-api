"""Privacy: consents, data exports and account deletions (Day 18)

learner_consents and consent_events: each person's consents and every change to them.
data_exports: a copy of a person's data, kept 7 days.
account_deletions: a deletion request (scheduled, cancelled or completed).

On the test database: four new empty tables; nothing else changes.

Revision ID: d4f9b3a7c2e8
Revises: c8e4a2f6b9d3
Create Date: 2026-11-02 20:14:13.312481

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f9b3a7c2e8"
down_revision: Union[str, Sequence[str], None] = "c8e4a2f6b9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "account_deletions",
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('scheduled', 'cancelled', 'completed')", name="ck_account_deletions_status"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("learner_id"),
    )
    op.create_table(
        "consent_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consent_events_learner", "consent_events", ["learner_id", "created_at"], unique=False
    )
    op.create_table(
        "data_exports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'ready', 'failed')", name="ck_data_exports_status"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_exports_learner", "data_exports", ["learner_id", "requested_at"], unique=False
    )
    op.create_table(
        "learner_consents",
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("learner_id", "key"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("learner_consents")
    op.drop_index("ix_data_exports_learner", table_name="data_exports")
    op.drop_table("data_exports")
    op.drop_index("ix_consent_events_learner", table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_table("account_deletions")
