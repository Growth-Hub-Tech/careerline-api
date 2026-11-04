"""Programmes and their clicks (Day 14)

programmes: Incubate and partner courses (reference data from seeds/programmes.json).
programme_roles, programme_skills: the job roles and skills each programme covers.
programme_clicks: every click on a programme, for referral reporting.

On the test database: four new tables, filled by the seed loader; nothing else changes.

Revision ID: a3f5c8e1d7b2
Revises: f1b8d4c2a6e9
Create Date: 2026-11-02 20:40:12.318404

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f5c8e1d7b2"
down_revision: Union[str, Sequence[str], None] = "f1b8d4c2a6e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "programmes",
        sa.Column("programme_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("duration_weeks", sa.Integer(), nullable=False),
        sa.Column("price_amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="NGN", nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider_type IN ('incubate', 'partner')", name="ck_programmes_provider_type"
        ),
        sa.CheckConstraint("mode IN ('online', 'in_person', 'hybrid')", name="ck_programmes_mode"),
        sa.CheckConstraint("duration_weeks >= 1", name="ck_programmes_duration"),
        sa.CheckConstraint("price_amount >= 0", name="ck_programmes_price"),
        sa.PrimaryKeyConstraint("programme_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "programme_roles",
        sa.Column("programme_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["programme_id"], ["programmes.programme_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["job_roles.role_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("programme_id", "role_id"),
    )
    op.create_table(
        "programme_skills",
        sa.Column("programme_id", sa.Integer(), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["programme_id"], ["programmes.programme_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.skill_id"]),
        sa.PrimaryKeyConstraint("programme_id", "skill_id"),
    )
    op.create_table(
        "programme_clicks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("click_id", sa.String(length=40), nullable=False),
        sa.Column("programme_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=True),
        sa.Column(
            "clicked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["programme_id"], ["programmes.programme_id"]),
        sa.ForeignKeyConstraint(["result_id"], ["test_attempt.attempt_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("click_id"),
    )
    op.create_index("ix_programme_clicks_learner", "programme_clicks", ["learner_id"])
    op.create_index(
        "ix_programme_clicks_programme", "programme_clicks", ["programme_id", "clicked_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_programme_clicks_programme", table_name="programme_clicks")
    op.drop_index("ix_programme_clicks_learner", table_name="programme_clicks")
    op.drop_table("programme_clicks")
    op.drop_table("programme_skills")
    op.drop_table("programme_roles")
    op.drop_table("programmes")
