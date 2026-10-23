"""Background worker entry point: `python -m app.worker` (the Render worker service runs this).

Day 3 only sets up the service: it starts, checks the database, logs a heartbeat and stops
cleanly when Render sends SIGTERM. The real jobs (scoring and AI recommendations off the
request, PDF reports, emails) arrive on Day 5.
"""

import asyncio
import signal

from sqlalchemy import text

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import engine

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


async def run(stop: asyncio.Event, heartbeat_seconds: float = HEARTBEAT_SECONDS) -> None:
    logger.info("worker_started", env=settings.APP_ENV)
    await check_database()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=heartbeat_seconds)
        except TimeoutError:
            logger.info("worker_heartbeat", database_ok=await check_database())
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
