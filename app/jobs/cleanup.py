"""Daily housekeeping: delete what is no longer needed after 30 days.

Finished background jobs (succeeded or dead), sent emails (the outbox row keeps the recipient's
address) and expired sign-in sessions. Each run schedules the next day's in the same
transaction as its deletes. Every process that runs jobs schedules today's when it starts, so a
restart also restarts a chain that stopped; the dedupe key makes that a no-op otherwise.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.jobs.queue import enqueue
from app.jobs.registry import PermanentJobError, job
from app.models.accounts import AuthSession
from app.models.email import EmailOutbox
from app.models.jobs import BackgroundJob

logger = get_logger(__name__)

JOB_KIND = "cleanup"
KEEP = timedelta(days=30)
RUN_AT = time(3, 0, tzinfo=UTC)  # 04:00 in Lagos


def _today() -> date:
    return datetime.now(UTC).date()


async def schedule_cleanup(
    session: AsyncSession, day: date, *, run_after: datetime | None = None
) -> int:
    return await enqueue(
        session,
        JOB_KIND,
        {"date": day.isoformat()},
        dedupe_key=f"cleanup:{day.isoformat()}",
        run_after=run_after,
    )


async def schedule_todays_cleanup() -> None:
    """For a process that runs jobs, when it starts. Without a database it only logs: the
    process keeps running, and the next start schedules it."""
    try:
        async with AsyncSessionLocal() as session:
            await schedule_cleanup(session, _today())
            await session.commit()
    except Exception as exc:
        logger.warning("cleanup_not_scheduled", error=type(exc).__name__)


@job(JOB_KIND)
async def cleanup(session: AsyncSession, payload: dict[str, Any]) -> None:
    try:
        day = date.fromisoformat(str(payload["date"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError(f"cleanup needs a date, got {payload!r}") from exc

    cutoff = datetime.now(UTC) - KEEP
    jobs = await session.execute(
        delete(BackgroundJob).where(
            BackgroundJob.status.in_(("succeeded", "dead")), BackgroundJob.finished_at < cutoff
        )
    )
    emails = await session.execute(
        delete(EmailOutbox).where(EmailOutbox.status == "sent", EmailOutbox.sent_at < cutoff)
    )
    sessions = await session.execute(delete(AuthSession).where(AuthSession.expires_at < cutoff))

    # The next day after this one (or after today, when this run is late: no catch-up runs)
    following = max(day, _today()) + timedelta(days=1)
    await schedule_cleanup(session, following, run_after=datetime.combine(following, RUN_AT))
    logger.info(
        "cleanup_done",
        jobs=jobs.rowcount,  # type: ignore[attr-defined]
        emails=emails.rowcount,  # type: ignore[attr-defined]
        sessions=sessions.rowcount,  # type: ignore[attr-defined]
        next_run=following.isoformat(),
    )
