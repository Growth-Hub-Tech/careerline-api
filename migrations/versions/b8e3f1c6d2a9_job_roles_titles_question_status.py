"""Job roles, the job-title ladder and question statuses (Day 8)

job_roles, job_role_skills, job_titles: reference data, loaded from seeds/job_roles.json and
seeds/job_titles.json by the seed loader. questions.status (ACTIVE, NEEDS_REVIEW, RETIRED) and
questions.quality_issues: set by the question-quality check when the seeds load; only ACTIVE
questions are served.

On the test database: three new empty tables, and every existing question starts ACTIVE with
no issues until the seeds load again (scripts/start.sh loads them when SEED_ON_START=true).

Revision ID: b8e3f1c6d2a9
Revises: a7d4e9b2c8f3
Create Date: 2026-10-30 09:12:31.402118

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b8e3f1c6d2a9"
down_revision: Union[str, Sequence[str], None] = "a7d4e9b2c8f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUESTION_STATUS = postgresql.ENUM(
    "ACTIVE", "NEEDS_REVIEW", "RETIRED", name="questionstatus", create_type=False
)
LEVEL_NAME = postgresql.ENUM(
    "BEGINNER", "JUNIOR", "MID", "ADVANCED", name="levelname", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    QUESTION_STATUS.create(op.get_bind(), checkfirst=False)
    op.add_column(
        "questions",
        sa.Column("status", QUESTION_STATUS, server_default="ACTIVE", nullable=False),
    )
    op.add_column(
        "questions",
        sa.Column(
            "quality_issues",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.create_table(
        "job_roles",
        sa.Column("role_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("track", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_pilot", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("track IN ('tech', 'revenue')", name="ck_job_roles_track"),
        sa.PrimaryKeyConstraint("role_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "job_role_skills",
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("target_level", LEVEL_NAME, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["job_roles.role_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"]),
        sa.PrimaryKeyConstraint("role_id", "skill_id"),
    )
    op.create_table(
        "job_titles",
        sa.Column("title_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("expected_level", LEVEL_NAME, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("title_id"),
        sa.UniqueConstraint("rank"),
        sa.UniqueConstraint("slug"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("job_titles")
    op.drop_table("job_role_skills")
    op.drop_table("job_roles")
    op.drop_column("questions", "quality_issues")
    op.drop_column("questions", "status")
    QUESTION_STATUS.drop(op.get_bind(), checkfirst=False)
