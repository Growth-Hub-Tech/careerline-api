"""Profiles (Day 28)

profiles: what each person tells us about themselves (headline, location, current role, years
of experience, goals, weekly hours, budget, LinkedIn), one row per person, made on their first
PATCH /profile. Who may see it is their share_profile_with_recruiters consent.

On the test database: one new empty table.

Revision ID: e8a3c6d1f4b5
Revises: d7f2b5c9a3e4
Create Date: 2026-11-02 21:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e8a3c6d1f4b5"
down_revision: Union[str, Sequence[str], None] = "d7f2b5c9a3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "profiles",
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("headline", sa.String(length=160), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("current_role", sa.String(length=120), nullable=True),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column(
            "goals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("weekly_hours", sa.Integer(), nullable=True),
        sa.Column("budget", sa.String(length=20), nullable=True),
        sa.Column("linkedin_url", sa.String(length=300), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("learner_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("profiles")
