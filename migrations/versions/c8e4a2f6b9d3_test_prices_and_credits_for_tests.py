"""Test prices and credits for tests (Day 17)

test_prices: what a test costs in credits, per skill (from seeds/test_prices.json; a skill not
listed is free).
credit_transactions.attempt_id: the test a charge or refund was for; one of each per test.

On the test database: one new table (filled by the seed loader) and one new empty column.

Revision ID: c8e4a2f6b9d3
Revises: b6d2e9f4a1c7
Create Date: 2026-11-02 20:03:02.447439

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e4a2f6b9d3"
down_revision: Union[str, Sequence[str], None] = "b6d2e9f4a1c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "test_prices",
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("price_credits", sa.Integer(), nullable=False),
        sa.CheckConstraint("price_credits >= 0", name="ck_test_prices_price"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("skill_id"),
    )
    op.add_column("credit_transactions", sa.Column("attempt_id", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_credit_transactions_attempt_reason", "credit_transactions", ["attempt_id", "reason"]
    )
    op.create_foreign_key(
        "credit_transactions_attempt_id_fkey",
        "credit_transactions",
        "test_attempt",
        ["attempt_id"],
        ["attempt_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "credit_transactions_attempt_id_fkey", "credit_transactions", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_credit_transactions_attempt_reason", "credit_transactions", type_="unique"
    )
    op.drop_column("credit_transactions", "attempt_id")
    op.drop_table("test_prices")
