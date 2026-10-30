"""Explanations of test questions (Day 11)

question_explanations: one AI explanation per question, kept for everyone, with a fingerprint
of the question it was made for (a changed question is explained again).

On the test database: one new empty table; nothing else changes.

Revision ID: d9a4b6e1f2c7
Revises: c4f7a2d9e1b3
Create Date: 2026-11-04 09:12:40.118204

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9a4b6e1f2c7"
down_revision: Union[str, Sequence[str], None] = "c4f7a2d9e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "question_explanations",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("question_digest", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["question_id"], ["questions.question_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("question_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("question_explanations")
