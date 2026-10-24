"""The queue itself: enqueue, claim (FOR UPDATE SKIP LOCKED + a lease), finish, fail.

Never lost: a job is a row, committed with the work that asked for it (enqueue uses the
caller's session, so a rolled-back request leaves no job). A claimed job has a lease
(locked_until); if its worker dies, the lease runs out and the next worker claims it again.

Never run twice: a dedupe key makes a second enqueue a no-op; SKIP LOCKED means two workers
never claim the same row; and a job can only be marked done by the worker that holds its
current lease (worker id + attempt number), in the same transaction as the handler's writes.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

MAX_ERROR_LENGTH = 2000


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


class LeaseLost(Exception):
    """The job's lease ran out and another worker took it: this worker must not finish it."""


async def enqueue(
    session: AsyncSession,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
) -> int:
    """Add a job in the caller's transaction. Returns its id (the existing one for a known key)."""
    inserted = await session.execute(
        text(
            "INSERT INTO background_jobs (kind, payload, dedupe_key, run_after, max_attempts) "
            "VALUES (:kind, CAST(:payload AS jsonb), :dedupe_key, COALESCE(:run_after, now()), "
            ":max_attempts) "
            "ON CONFLICT (dedupe_key) DO NOTHING RETURNING id"
        ),
        {
            "kind": kind,
            "payload": json.dumps(payload or {}),
            "dedupe_key": dedupe_key,
            "run_after": run_after,
            "max_attempts": max_attempts or settings.JOB_MAX_ATTEMPTS,
        },
    )
    job_id = inserted.scalar_one_or_none()
    if job_id is None:
        existing = await session.execute(
            text("SELECT id FROM background_jobs WHERE dedupe_key = :key"), {"key": dedupe_key}
        )
        job_id = existing.scalar_one()
    return int(job_id)


async def claim(
    session: AsyncSession, worker_id: str, *, limit: int, lease_seconds: float
) -> list[ClaimedJob]:
    """Claim up to `limit` due jobs for this worker. The caller commits to publish the lease."""
    rows = await session.execute(
        text(
            "WITH due AS ("
            "  SELECT id FROM background_jobs"
            "  WHERE (status = 'queued' AND run_after <= now())"
            "     OR (status = 'running' AND locked_until < now())"
            "  ORDER BY run_after, id"
            "  FOR UPDATE SKIP LOCKED"
            "  LIMIT :limit"
            ") "
            "UPDATE background_jobs AS job SET"
            "  status = 'running', attempts = job.attempts + 1, locked_by = :worker,"
            "  locked_until = now() + make_interval(secs => :lease), updated_at = now() "
            "FROM due WHERE job.id = due.id "
            "RETURNING job.id, job.kind, job.payload, job.attempts, job.max_attempts"
        ),
        {"limit": limit, "worker": worker_id, "lease": float(lease_seconds)},
    )
    jobs = [
        ClaimedJob(
            id=row.id,
            kind=row.kind,
            payload=dict(row.payload or {}),
            attempts=row.attempts,
            max_attempts=row.max_attempts,
        )
        for row in rows
    ]
    return sorted(jobs, key=lambda job: job.id)


async def mark_succeeded(session: AsyncSession, job: ClaimedJob, worker_id: str) -> None:
    """Mark the job done in the handler's transaction; raises LeaseLost if it is not ours anymore."""
    result = await session.execute(
        text(
            "UPDATE background_jobs SET status = 'succeeded', finished_at = now(),"
            " locked_by = NULL, locked_until = NULL, last_error = NULL, updated_at = now() "
            "WHERE id = :id AND status = 'running' AND locked_by = :worker AND attempts = :attempts"
        ),
        {"id": job.id, "worker": worker_id, "attempts": job.attempts},
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise LeaseLost(f"job {job.id} is no longer held by {worker_id}")


async def mark_failed(
    session: AsyncSession,
    job: ClaimedJob,
    worker_id: str,
    error: str,
    *,
    retry_in_seconds: float,
    permanent: bool = False,
) -> str | None:
    """Schedule a retry, or dead-letter the job after its last attempt. Returns the new status."""
    dead = permanent or job.attempts >= job.max_attempts
    result = await session.execute(
        text(
            "UPDATE background_jobs SET"
            "  status = :status,"
            "  run_after = CASE WHEN :dead THEN run_after"
            "              ELSE now() + make_interval(secs => :retry_in) END,"
            "  finished_at = CASE WHEN :dead THEN now() ELSE NULL END,"
            "  last_error = :error, locked_by = NULL, locked_until = NULL, updated_at = now() "
            "WHERE id = :id AND status = 'running' AND locked_by = :worker AND attempts = :attempts"
        ),
        {
            "status": "dead" if dead else "queued",
            "dead": dead,
            "retry_in": float(retry_in_seconds),
            "error": error[:MAX_ERROR_LENGTH],
            "id": job.id,
            "worker": worker_id,
            "attempts": job.attempts,
        },
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return None  # another worker holds it now; it decides
    return "dead" if dead else "queued"
