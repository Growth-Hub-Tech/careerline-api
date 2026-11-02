"""Team roster and seats (Day 21)

team_members: the people an organisation audits, each mapped to a job role.
organisations.seats_total: how many people the roster may hold (25 until an organisation plan
sets it, Days 25-26).
invitations.team_member_id: the roster entry a team invitation tests.

On the test database: one new empty table; existing organisations get 25 seats.

Revision ID: f3a9c1e5b7d4
Revises: e7a1c5d9f3b2
Create Date: 2026-11-02 21:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a9c1e5b7d4"
down_revision: Union[str, Sequence[str], None] = "e7a1c5d9f3b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "organisations",
        sa.Column("seats_total", sa.Integer(), server_default="25", nullable=False),
    )
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("department", sa.String(length=80), nullable=True),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["job_roles.role_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "email", name="uq_team_members_organisation_email"),
    )
    op.create_index(
        "ix_team_members_organisation_name",
        "team_members",
        ["organisation_id", "full_name"],
        unique=False,
    )
    op.add_column("invitations", sa.Column("team_member_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "invitations_team_member_id_fkey",
        "invitations",
        "team_members",
        ["team_member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_invitations_team_member", "invitations", ["team_member_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_invitations_team_member", table_name="invitations")
    op.drop_constraint("invitations_team_member_id_fkey", "invitations", type_="foreignkey")
    op.drop_column("invitations", "team_member_id")
    op.drop_index("ix_team_members_organisation_name", table_name="team_members")
    op.drop_table("team_members")
    op.drop_column("organisations", "seats_total")
