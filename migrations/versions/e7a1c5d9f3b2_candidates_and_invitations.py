"""Candidates and invitations (Day 19)

candidates: an organisation's candidates (one per email per organisation).
invitations: links to take one catalogue test (sent, accepted, completed or revoked).

On the test database: two new empty tables; nothing else changes.

Revision ID: e7a1c5d9f3b2
Revises: d4f9b3a7c2e8
Create Date: 2026-11-02 20:26:00.021654

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c5d9f3b2"
down_revision: Union[str, Sequence[str], None] = "d4f9b3a7c2e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by"], ["learner.learner_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["job_roles.role_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "email", name="uq_candidates_organisation_email"),
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="sent", nullable=False),
        sa.Column("sent_by", sa.Integer(), nullable=True),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.Integer(), nullable=True),
        sa.Column("attempt_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('candidate', 'team_member')", name="ck_invitations_kind"),
        sa.CheckConstraint(
            "status IN ('sent', 'accepted', 'completed', 'revoked')", name="ck_invitations_status"
        ),
        sa.ForeignKeyConstraint(["accepted_by"], ["learner.learner_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attempt_id"], ["test_attempt.attempt_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sent_by"], ["learner.learner_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.skill_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_invitations_candidate", "invitations", ["candidate_id"], unique=False)
    op.create_index(
        "ix_invitations_organisation", "invitations", ["organisation_id", "sent_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_invitations_organisation", table_name="invitations")
    op.drop_index("ix_invitations_candidate", table_name="invitations")
    op.drop_table("invitations")
    op.drop_table("candidates")
