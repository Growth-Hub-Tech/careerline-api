"""Audit re-tests (Day 24)

audits.baseline_audit_id: the audit a re-test repeats (the same people, the same tests), so the
change in scores can be worked out.

On the test database: one empty column.

Revision ID: c6e1a4b8f3d2
Revises: b5d9f3a7e2c1
Create Date: 2026-11-02 21:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6e1a4b8f3d2"
down_revision: Union[str, Sequence[str], None] = "b5d9f3a7e2c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("audits", sa.Column("baseline_audit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "audits_baseline_audit_id_fkey",
        "audits",
        "audits",
        ["baseline_audit_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("audits_baseline_audit_id_fkey", "audits", type_="foreignkey")
    op.drop_column("audits", "baseline_audit_id")
