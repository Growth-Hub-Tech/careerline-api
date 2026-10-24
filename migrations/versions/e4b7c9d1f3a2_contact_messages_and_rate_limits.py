"""Contact form messages and the rate limiter (Day 5)

contact_messages: what people send through POST /api/v1/contact (ticket_id unique).
rate_limit_events: one row per counted action, bucket = kind + keyed hash (no email or IP
in clear); used by the contact form now and by sign-in limits later. Only adds tables.

Revision ID: e4b7c9d1f3a2
Revises: d2e8f1a4c6b9
Create Date: 2026-10-24 20:38:47.079180

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b7c9d1f3a2"
down_revision: Union[str, Sequence[str], None] = "d2e8f1a4c6b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "contact_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticket_id", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("topic", sa.String(length=40), nullable=False),
        sa.Column("organisation", sa.String(length=160), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_id", name="uq_contact_messages_ticket_id"),
    )
    op.create_table(
        "rate_limit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bucket", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rate_limit_events_bucket_created_at",
        "rate_limit_events",
        ["bucket", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_rate_limit_events_bucket_created_at", table_name="rate_limit_events")
    op.drop_table("rate_limit_events")
    op.drop_table("contact_messages")
