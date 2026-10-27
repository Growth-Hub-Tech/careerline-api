"""Claims due jobs and runs them: `JobRunner().run_forever(stop)`.

Each job runs in its own database transaction. The handler's writes and "this job is done"
commit together; if the handler raises, times out, or the lease was lost, everything rolls
back and the job is retried later (growing backoff) or dead-lettered after max_attempts.
"""

import asyncio
import os
import socket
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.jobs import registry
from app.jobs.queue import (
    ClaimedJob,
    LeaseLost,
    claim,
    mark_failed,
    mark_succeeded,
    renew_lease,
)

logger = get_logger(__name__)


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class JobRunner:
    def __init__(
        self,
        worker_id: str | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        lease_seconds: float | None = None,
        timeout_seconds: float | None = None,
        poll_seconds: float | None = None,
        batch_size: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
    ):
        self.worker_id = worker_id or default_worker_id()
        self.session_factory = session_factory or AsyncSessionLocal
        self.lease_seconds = lease_seconds or settings.JOB_LEASE_SECONDS
        # Stop a handler well before its lease runs out, so nobody else takes it meanwhile
        self.timeout_seconds = timeout_seconds or max(1.0, self.lease_seconds * 0.8)
        self.poll_seconds = poll_seconds or settings.JOB_POLL_SECONDS
        self.batch_size = batch_size or settings.JOB_BATCH_SIZE
        self.retry_base_seconds = retry_base_seconds or settings.JOB_RETRY_BASE_SECONDS
        self.retry_max_seconds = retry_max_seconds or settings.JOB_RETRY_MAX_SECONDS
        registry.load_handlers()

    def backoff_seconds(self, attempts: int) -> float:
        return min(self.retry_base_seconds * 2 ** max(attempts - 1, 0), self.retry_max_seconds)

    async def run_once(self) -> int:
        """Claim one batch and run it. Returns how many jobs were claimed (0 = queue empty)."""
        async with self.session_factory() as session:
            jobs = await claim(
                session, self.worker_id, limit=self.batch_size, lease_seconds=self.lease_seconds
            )
            await session.commit()
        for job in jobs:
            await self._run(job)
        return len(jobs)

    async def _run(self, job: ClaimedJob) -> None:
        log = logger.bind(job_id=job.id, kind=job.kind, attempt=job.attempts)
        handler = registry.HANDLERS.get(job.kind)
        if handler is None:
            await self._fail(job, f"no handler for job kind {job.kind!r}", permanent=True)
            log.error("job_dead", reason="no handler")
            return
        if job.attempts > job.max_attempts:
            # Its worker died on every attempt (the lease ran out each time)
            await self._fail(job, "the worker stopped during every attempt", permanent=True)
            log.error("job_dead", reason="lease expired on every attempt")
            return
        try:
            async with self.session_factory() as session:
                # The batch shares one lease from claim time: give this job a full lease of its
                # own now, or skip it if another worker took it over while earlier jobs ran
                if not await renew_lease(session, job, self.worker_id, self.lease_seconds):
                    raise LeaseLost(f"job {job.id} is no longer held by {self.worker_id}")
                await session.commit()
                await asyncio.wait_for(handler(session, job.payload), timeout=self.timeout_seconds)
                await mark_succeeded(session, job, self.worker_id)
                await session.commit()
        except LeaseLost:
            log.warning("job_lease_lost")
            return
        except TimeoutError:
            status = await self._fail(job, f"timed out after {self.timeout_seconds:g}s")
            log.error("job_failed", reason="timeout", status=status)
            return
        except registry.PermanentJobError as exc:
            await self._fail(job, f"{type(exc).__name__}: {exc}", permanent=True)
            log.exception("job_dead", reason="permanent error")
            return
        except Exception as exc:
            status = await self._fail(job, f"{type(exc).__name__}: {exc}")
            # The stack trace goes to the log; the row keeps a one-line reason
            log.exception("job_failed", status=status)
            return
        log.info("job_succeeded")

    async def _fail(self, job: ClaimedJob, error: str, *, permanent: bool = False) -> str | None:
        async with self.session_factory() as session:
            status = await mark_failed(
                session,
                job,
                self.worker_id,
                error,
                retry_in_seconds=self.backoff_seconds(job.attempts),
                permanent=permanent,
            )
            await session.commit()
        return status

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Run jobs until `stop` is set. A database outage is logged and retried, never fatal."""
        logger.info("job_runner_started", worker_id=self.worker_id)
        failures = 0
        while not stop.is_set():
            try:
                claimed = await self.run_once()
                failures = 0
            except Exception as exc:
                failures += 1
                claimed = 0
                logger.warning("job_poll_failed", error=type(exc).__name__, failures=failures)
            if claimed:
                continue  # more may be waiting
            wait = self.poll_seconds if not failures else min(30.0, self.poll_seconds * 2**failures)
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except TimeoutError:
                pass
        logger.info("job_runner_stopped", worker_id=self.worker_id)
