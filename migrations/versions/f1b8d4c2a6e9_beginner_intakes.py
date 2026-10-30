"""The beginner path's intakes (Day 13)

beginner_intakes: every intake a person submits (questionnaire version, answers) with the
career paths it gave at the time.

On the test database: one new empty table; nothing else changes.

Revision ID: f1b8d4c2a6e9
Revises: e3c7f9a1b5d8
Create Date: 2026-11-06 09:20:31.447120

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1b8d4c2a6e9"
down_revision: Union[str, Sequence[str], None] = "e3c7f9a1b5d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "beginner_intakes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recommendations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_beginner_intakes_learner", "beginner_intakes", ["learner_id", "submitted_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_beginner_intakes_learner", table_name="beginner_intakes")
    op.drop_table("beginner_intakes")
