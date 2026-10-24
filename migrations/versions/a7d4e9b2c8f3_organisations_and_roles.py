"""Organisations and their accounts' roles (Day 7)

organisations: the companies. organisation_members: an account's role in an organisation
(owner, admin or recruiter), one organisation per account. Permissions per role live in
app/core/permissions.py, not in the database.

On the test database: adds two empty tables; nothing existing changes. The demo company
(id 41) and its accounts are loaded by `python -m app.db.demo` when DEMO_DATA_ON_START=true.

Revision ID: a7d4e9b2c8f3
Revises: f6c3a8e2d5b1
Create Date: 2026-10-24 21:04:45.907166

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d4e9b2c8f3"
down_revision: Union[str, Sequence[str], None] = "f6c3a8e2d5b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "organisations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.Column("size", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organisation_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("learner_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'recruiter')", name="ck_organisation_members_role"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learner.learner_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("learner_id", name="uq_organisation_members_learner_id"),
    )
    op.create_index(
        "ix_organisation_members_organisation_id",
        "organisation_members",
        ["organisation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_organisation_members_organisation_id", table_name="organisation_members")
    op.drop_table("organisation_members")
    op.drop_table("organisations")
