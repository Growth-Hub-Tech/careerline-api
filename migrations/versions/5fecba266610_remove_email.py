"""Remove email: CareerLine sends no email, and invitations are in-app

Dropped: email_outbox and test_mailbox_messages (every email went through them),
contact_messages (the contact form is gone), account_tokens (only the email links used them)
and learner.email_verified_at (email confirmation is gone). Queued send_email jobs are deleted:
no handler is left for them. New: ix_invitations_email, for GET /invitations/received.

On the test database: four tables and one column are dropped, with their rows; the downgrade
puts the empty tables and the column back.

Revision ID: 5fecba266610
Revises: e8a3c6d1f4b5
Create Date: 2026-11-25 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5fecba266610"
down_revision: Union[str, Sequence[str], None] = "e8a3c6d1f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DELETE FROM background_jobs WHERE kind = 'send_email'")
    op.drop_index("ix_test_mailbox_messages_to_email", table_name="test_mailbox_messages")
    op.drop_table("test_mailbox_messages")
    op.drop_table("email_outbox")
    op.drop_table("contact_messages")
    op.drop_index("ix_account_tokens_learner_id_purpose", table_name="account_tokens")
    op.drop_table("account_tokens")
    op.drop_column("learner", "email_verified_at")
    op.create_index("ix_invitations_email", "invitations", ["email"], unique=False)


def downgrade() -> None:
    """Downgrade schema: the tables and the column come back empty."""
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.add_column(
        "learner", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'password_reset')", name="ck_account_tokens_purpose"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_account_tokens_token_hash"),
    )
    op.create_index(
        "ix_account_tokens_learner_id_purpose",
        "account_tokens",
        ["learner_id", "purpose"],
        unique=False,
    )
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
