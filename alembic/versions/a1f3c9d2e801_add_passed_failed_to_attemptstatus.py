"""Add PASSED and FAILED to the attemptstatus enum

The scoring code saves PASSED / FAILED, but the initial migration created
attemptstatus with only IN_PROGRESS, COMPLETED and CANCELLED, so every submit
failed with "invalid input value for enum attemptstatus".

Revision ID: a1f3c9d2e801
Revises: e17f129e4f88
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1f3c9d2e801'
down_revision: Union[str, Sequence[str], None] = 'e17f129e4f88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS makes this safe if the values were already added by hand.
    # Postgres 12+ allows ADD VALUE inside Alembic's transaction (the new value just
    # can't be used in that same transaction, and this migration doesn't use it).
    op.execute("ALTER TYPE attemptstatus ADD VALUE IF NOT EXISTS 'PASSED'")
    op.execute("ALTER TYPE attemptstatus ADD VALUE IF NOT EXISTS 'FAILED'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum type. Leaving them is harmless.
    pass
