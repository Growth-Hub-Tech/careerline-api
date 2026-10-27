"""Email: the email_outbox every email goes through, and test_mailbox_messages (Day 5)

email_outbox: one row per email, delivered once by the send_email job (dedupe_key unique;
the bodies are emptied once sent). test_mailbox_messages: the emails of the test server
(EMAIL_BACKEND=test_mailbox), read by GET /api/v1/test-mailbox. Only adds tables.

Revision ID: d2e8f1a4c6b9
Revises: c5a1d0e7b2f4
Create Date: 2026-10-24 20:34:27.326830

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e8f1a4c6b9"
down_revision: Union[str, Sequence[str], None] = "c5a1d0e7b2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("to_email", sa.String(length=320), nullable=False),
        sa.Column("template", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("backend", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'sent')", name="ck_email_outbox_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_email_outbox_dedupe_key"),
    )
    op.create_table(
        "test_mailbox_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("to_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_test_mailbox_messages_to_email", "test_mailbox_messages", ["to_email"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_test_mailbox_messages_to_email", table_name="test_mailbox_messages")
    op.drop_table("test_mailbox_messages")
    op.drop_table("email_outbox")
