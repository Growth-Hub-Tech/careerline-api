"""PDF skill reports of results (Day 12)

result_reports: one row per result (a finished adaptive test): status generating/ready/failed,
the PDF itself, and a version that goes up when it is made again.

On the test database: one new empty table; nothing else changes.

Revision ID: e3c7f9a1b5d8
Revises: d9a4b6e1f2c7
Create Date: 2026-11-05 09:05:12.604311

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3c7f9a1b5d8"
down_revision: Union[str, Sequence[str], None] = "d9a4b6e1f2c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "result_reports",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="generating", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed')", name="ck_result_reports_status"
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["test_attempt.attempt_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attempt_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("result_reports")
