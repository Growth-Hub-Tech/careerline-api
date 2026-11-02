"""Organisation targets (Day 23)

organisation_targets: the level each job role should reach in each skill (with an optional due
date), set by the organisation; replaced as a whole by PUT /organisations/{id}/targets.

On the test database: one new empty table.

Revision ID: b5d9f3a7e2c1
Revises: a4c8e2f6d1b9
Create Date: 2026-11-02 21:25:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b5d9f3a7e2c1"
down_revision: Union[str, Sequence[str], None] = "a4c8e2f6d1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEVEL_NAME = postgresql.ENUM(
    "BEGINNER", "JUNIOR", "MID", "ADVANCED", name="levelname", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "organisation_targets",
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("target_level", LEVEL_NAME, nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["job_roles.role_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"]),
        sa.PrimaryKeyConstraint("organisation_id", "role_id", "skill_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("organisation_targets")
