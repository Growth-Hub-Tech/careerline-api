"""Adaptive test-taking and the skill history (Day 10)

test_attempt: test_format (existing rows are the retired "fixed" test), question_count,
expires_at, ability, confidence, ended_by; status EXPIRED. attempt_question: the served level,
when it was served, and the answer (selected option, right or not, when). skill_history: one
entry per finished test.

On the test database: existing attempts become test_format "fixed" and keep everything they
had (old PASSED/FAILED results stay readable); one new empty table.

Revision ID: c4f7a2d9e1b3
Revises: b8e3f1c6d2a9
Create Date: 2026-11-03 08:41:17.220463

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4f7a2d9e1b3"
down_revision: Union[str, Sequence[str], None] = "b8e3f1c6d2a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEVEL_NAME = postgresql.ENUM(
    "BEGINNER", "JUNIOR", "MID", "ADVANCED", name="levelname", create_type=False
)
OLD_STATUSES = ("IN_PROGRESS", "COMPLETED", "CANCELLED", "PASSED", "FAILED")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE attemptstatus ADD VALUE IF NOT EXISTS 'EXPIRED'")
    op.add_column(
        "test_attempt",
        sa.Column("test_format", sa.String(length=20), server_default="fixed", nullable=False),
    )
    op.add_column("test_attempt", sa.Column("question_count", sa.Integer(), nullable=True))
    op.add_column(
        "test_attempt", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "test_attempt", sa.Column("ability", sa.Numeric(precision=5, scale=3), nullable=True)
    )
    op.add_column(
        "test_attempt", sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True)
    )
    op.add_column("test_attempt", sa.Column("ended_by", sa.String(length=20), nullable=True))
    op.add_column("attempt_question", sa.Column("level", LEVEL_NAME, nullable=True))
    op.add_column(
        "attempt_question", sa.Column("served_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("attempt_question", sa.Column("selected_option_id", sa.Integer(), nullable=True))
    op.add_column("attempt_question", sa.Column("is_correct", sa.Boolean(), nullable=True))
    op.add_column(
        "attempt_question", sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "attempt_question_selected_option_id_fkey",
        "attempt_question",
        "options",
        ["selected_option_id"],
        ["option_id"],
    )
    op.create_table(
        "skill_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("level", LEVEL_NAME, nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "strengths",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "weaknesses",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["test_attempt.attempt_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id"),
    )
    op.create_index(
        "ix_skill_history_learner_skill",
        "skill_history",
        ["learner_id", "skill_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_skill_history_learner_skill", table_name="skill_history")
    op.drop_table("skill_history")
    op.drop_constraint(
        "attempt_question_selected_option_id_fkey", "attempt_question", type_="foreignkey"
    )
    for column in ("answered_at", "is_correct", "selected_option_id", "served_at", "level"):
        op.drop_column("attempt_question", column)
    for column in (
        "ended_by",
        "confidence",
        "ability",
        "expires_at",
        "question_count",
        "test_format",
    ):
        op.drop_column("test_attempt", column)
    # Postgres cannot drop one value of an enum type: expired attempts become cancelled, then the
    # type is rebuilt without EXPIRED
    op.execute(
        "UPDATE test_attempt SET attempt_status = 'CANCELLED' WHERE attempt_status = 'EXPIRED'"
    )
    op.execute("ALTER TYPE attemptstatus RENAME TO attemptstatus_day10")
    values = ", ".join(f"'{value}'" for value in OLD_STATUSES)
    op.execute(f"CREATE TYPE attemptstatus AS ENUM ({values})")
    op.execute(
        "ALTER TABLE test_attempt ALTER COLUMN attempt_status TYPE attemptstatus "
        "USING attempt_status::text::attemptstatus"
    )
    op.execute("DROP TYPE attemptstatus_day10")
