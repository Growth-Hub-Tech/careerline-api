"""Accounts: sessions, email-link tokens and email confirmation (Day 6)

auth_sessions: one row per signed-in device; the access token names it (sid), so sign-out
and password reset end tokens at once. account_tokens: single-use, expiring tokens of the
confirmation and reset links, stored as SHA-256. learner.email_verified_at: NULL until the
confirmation link is opened (existing learners start unconfirmed).

On the test database: adds two tables and one nullable column; existing rows are untouched.
Tokens issued before this deploy have no session id, so everyone signs in once more.

Revision ID: f6c3a8e2d5b1
Revises: e4b7c9d1f3a2
Create Date: 2026-10-24 20:52:45.055210

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6c3a8e2d5b1"
down_revision: Union[str, Sequence[str], None] = "e4b7c9d1f3a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
        "auth_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=30), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_sessions_learner_id", "auth_sessions", ["learner_id"], unique=False)
    op.add_column(
        "learner", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("learner", "email_verified_at")
    op.drop_index("ix_auth_sessions_learner_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_account_tokens_learner_id_purpose", table_name="account_tokens")
    op.drop_table("account_tokens")
