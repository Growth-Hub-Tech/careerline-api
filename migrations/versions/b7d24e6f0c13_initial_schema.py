"""Initial schema: every table, in one migration

Replaces the four hand-built migrations (38a2cb03e747 initial tables,
e17f129e4f88 hashed_password, a1f3c9d2e801 PASSED/FAILED attempt statuses,
b7d24e6f0c13 attempt_question) with one clean starting point. The schema it
creates is exactly what those four produced (checked with pg_dump --schema-only
on Postgres 16: no difference).

It keeps the revision id of the old head, b7d24e6f0c13, on purpose: a database
that was already migrated (the Render test database) is at b7d24e6f0c13, so it
is already at head and nothing runs; an empty database gets the whole schema.
A database stuck at one of the three older revisions must be reset (see
docs/database.md).

Reference data (levels, skills, questions, ...) is not created here: load it
with `python -m app.db.seed`.

Revision ID: b7d24e6f0c13
Revises:
Create Date: 2026-10-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d24e6f0c13"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learner",
        sa.Column("learner_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column(
            "registration_date", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "learner_status", sa.Enum("ACTIVE", "INACTIVE", name="learnerstatus"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("learner_id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "proficiency_level",
        sa.Column("level_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "level_name",
            sa.Enum("BEGINNER", "JUNIOR", "MID", "ADVANCED", name="levelname"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("level_id"),
        sa.UniqueConstraint("level_name"),
    )
    op.create_table(
        "skills",
        sa.Column("skill_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("skill_descr", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("skill_id"),
    )
    op.create_table(
        "behavioural_questions",
        sa.Column("question_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "question_type",
            sa.Enum("GENERAL", "SKILL_SPECIFIC", name="questiontype"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.skill_id"],
        ),
        sa.PrimaryKeyConstraint("question_id"),
    )
    op.create_table(
        "level_threshold",
        sa.Column("threshold_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("level_id", sa.Integer(), nullable=False),
        sa.Column("min_score", sa.Integer(), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["level_id"],
            ["proficiency_level.level_id"],
        ),
        sa.PrimaryKeyConstraint("threshold_id"),
    )
    op.create_table(
        "subskills",
        sa.Column("subskill_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("subskill_name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.skill_id"],
        ),
        sa.PrimaryKeyConstraint("subskill_id"),
    )
    op.create_table(
        "test_attempt",
        sa.Column("attempt_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("declared_level_id", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("overall_percentage", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("assigned_level_id", sa.Integer(), nullable=True),
        sa.Column(
            "attempt_status",
            sa.Enum(
                "IN_PROGRESS", "COMPLETED", "CANCELLED", "PASSED", "FAILED", name="attemptstatus"
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_level_id"],
            ["proficiency_level.level_id"],
        ),
        sa.ForeignKeyConstraint(
            ["declared_level_id"],
            ["proficiency_level.level_id"],
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner.learner_id"],
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.skill_id"],
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_table(
        "attempt_difficulty_score",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column(
            "difficulty_level",
            sa.Enum("BEGINNER", "JUNIOR", "MID", "ADVANCED", name="levelname"),
            nullable=False,
        ),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("percentage_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempt.attempt_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "attempt_subskill_score",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("subskill_id", sa.Integer(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("percentage_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempt.attempt_id"],
        ),
        sa.ForeignKeyConstraint(
            ["subskill_id"],
            ["subskills.subskill_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "learner_level",
        sa.Column("learner_level_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=True),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("level_id", sa.Integer(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempt.attempt_id"],
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner.learner_id"],
        ),
        sa.ForeignKeyConstraint(
            ["level_id"],
            ["proficiency_level.level_id"],
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.skill_id"],
        ),
        sa.PrimaryKeyConstraint("learner_level_id"),
    )
    op.create_table(
        "learner_profile",
        sa.Column("profile_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempt.attempt_id"],
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner.learner_id"],
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["behavioural_questions.question_id"],
        ),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_table(
        "questions",
        sa.Column("question_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subskill_id", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "difficulty_level",
            sa.Enum("BEGINNER", "JUNIOR", "MID", "ADVANCED", name="levelname"),
            nullable=False,
        ),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["subskill_id"],
            ["subskills.subskill_id"],
        ),
        sa.PrimaryKeyConstraint("question_id"),
    )
    op.create_table(
        "subskill_recommendation",
        sa.Column("recommendation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("percentage_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("subskill_id", sa.Integer(), nullable=False),
        sa.Column("recommendation_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempt.attempt_id"],
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learner.learner_id"],
        ),
        sa.ForeignKeyConstraint(
            ["subskill_id"],
            ["subskills.subskill_id"],
        ),
        sa.PrimaryKeyConstraint("recommendation_id"),
    )
    op.create_table(
        "options",
        sa.Column("option_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("option_text", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.question_id"],
        ),
        sa.PrimaryKeyConstraint("option_id"),
    )
    op.create_table(
        "learner_answer",
        sa.Column("learner_answer_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("selected_option_id", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["test_attempt.attempt_id"],
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.question_id"],
        ),
        sa.ForeignKeyConstraint(
            ["selected_option_id"],
            ["options.option_id"],
        ),
        sa.PrimaryKeyConstraint("learner_answer_id"),
    )
    op.create_table(
        "attempt_question",
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["test_attempt.attempt_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.question_id"]),
        sa.PrimaryKeyConstraint("attempt_id", "question_id"),
    )


def downgrade() -> None:
    op.drop_table("attempt_question")
    op.drop_table("learner_answer")
    op.drop_table("options")
    op.drop_table("subskill_recommendation")
    op.drop_table("questions")
    op.drop_table("learner_profile")
    op.drop_table("learner_level")
    op.drop_table("attempt_subskill_score")
    op.drop_table("attempt_difficulty_score")
    op.drop_table("test_attempt")
    op.drop_table("subskills")
    op.drop_table("level_threshold")
    op.drop_table("behavioural_questions")
    op.drop_table("skills")
    op.drop_table("proficiency_level")
    op.drop_table("learner")
    # The tables are gone; their enum types are not dropped with them
    for enum_type in ("attemptstatus", "questiontype", "levelname", "learnerstatus"):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
