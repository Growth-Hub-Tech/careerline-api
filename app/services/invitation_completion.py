"""Day 20: a finished test completes the invitation it was started from (kept apart from
app/services/recruiting.py, which starts tests, so the test-taking service can call it)."""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.recruiting import Invitation

logger = get_logger(__name__)


async def complete_invitations(db: AsyncSession, attempt_id: int) -> None:
    result = await db.execute(
        update(Invitation)
        .where(Invitation.attempt_id == attempt_id, Invitation.status == "accepted")
        .values(status="completed", completed_at=datetime.now(UTC))
        .returning(Invitation.id)
    )
    for invitation_id in result.scalars():
        logger.info("invitation_completed", invitation_id=invitation_id, attempt_id=attempt_id)
