"""Background worker entry point: `python -m app.worker` (a worker service runs this).

It runs the background jobs (app/jobs): claims due jobs from the background_jobs table, runs
them, retries failures and dead-letters the hopeless ones, and stops cleanly on SIGTERM. Any
number of workers can run at once; they never run the same job.

The free test server has no worker service: there RUN_JOBS_IN_WEB=true runs the same loop
inside the API process instead (app/main.py).
"""

import asyncio
import signal

from sqlalchemy import text

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import engine
from app.jobs.runner import JobRunner

logger = get_logger("app.worker")

HEARTBEAT_SECONDS = 60.0


async def check_database() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("worker_database_unreachable", error=type(exc).__name__)
        return False


async def _heartbeat(stop: asyncio.Event, heartbeat_seconds: float) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=heartbeat_seconds)
        except TimeoutError:
            logger.info("worker_heartbeat", database_ok=await check_database())


async def run(
    stop: asyncio.Event,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    runner: JobRunner | None = None,
) -> None:
    logger.info("worker_started", env=settings.APP_ENV)
    await check_database()
    runner = runner or JobRunner()
    await asyncio.gather(runner.run_forever(stop), _heartbeat(stop, heartbeat_seconds))
    await engine.dispose()
    logger.info("worker_stopped")


def main() -> None:
    configure_logging()

    async def _main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop.set)
        await run(stop)

    asyncio.run(_main())


if __name__ == "__main__":
    main()
