"""Audits (Day 22)

audits: one round of testing an organisation's team for some job roles (draft until started).
audit_members: who is in an audit, with the role they had then.
invitations.audit_id: the audit that sent a team invitation.

On the test database: two new empty tables and an empty column.

Revision ID: a4c8e2f6d1b9
Revises: f3a9c1e5b7d4
Create Date: 2026-11-02 21:15:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a4c8e2f6d1b9"
down_revision: Union[str, Sequence[str], None] = "f3a9c1e5b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role_ids", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["learner.learner_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audits_organisation", "audits", ["organisation_id", "created_at"], unique=False
    )
    op.create_table(
        "audit_members",
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("team_member_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["job_roles.role_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_member_id"], ["team_members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("audit_id", "team_member_id"),
    )
    op.add_column("invitations", sa.Column("audit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "invitations_audit_id_fkey",
        "invitations",
        "audits",
        ["audit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_invitations_audit", "invitations", ["audit_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_invitations_audit", table_name="invitations")
    op.drop_constraint("invitations_audit_id_fkey", "invitations", type_="foreignkey")
    op.drop_column("invitations", "audit_id")
    op.drop_table("audit_members")
    op.drop_index("ix_audits_organisation", table_name="audits")
    op.drop_table("audits")
