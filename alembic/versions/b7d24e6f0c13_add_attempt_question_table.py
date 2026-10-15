"""Add attempt_question: the exact questions served in each attempt

Submit uses it to accept only answers to questions that were actually served,
one answer per question, so a score can no longer go above 100%.

Revision ID: b7d24e6f0c13
Revises: a1f3c9d2e801
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7d24e6f0c13'
down_revision: Union[str, Sequence[str], None] = 'a1f3c9d2e801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'attempt_question',
        sa.Column('attempt_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['attempt_id'], ['test_attempt.attempt_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['questions.question_id']),
        sa.PrimaryKeyConstraint('attempt_id', 'question_id'),
    )


def downgrade() -> None:
    op.drop_table('attempt_question')
