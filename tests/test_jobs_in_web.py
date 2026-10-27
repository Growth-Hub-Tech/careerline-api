"""Day 5: on the free test server there is no worker service, so the web process runs the jobs.

RUN_JOBS_IN_WEB=true starts the job loop inside the API process (app/main.py lifespan);
production runs `python -m app.worker` as its own service and leaves it false.
"""

import asyncio

from app import main
from app.core.config import Settings, settings


def test_jobs_do_not_run_in_the_web_process_by_default(monkeypatch):
    monkeypatch.delenv("RUN_JOBS_IN_WEB", raising=False)
    assert Settings(DATABASE_URL="postgresql://x/y", SECRET_KEY="k").RUN_JOBS_IN_WEB is False


async def test_the_web_process_starts_and_stops_the_job_loop_when_asked(monkeypatch):
    started = asyncio.Event()
    stopped = asyncio.Event()

    class FakeRunner:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def run_forever(self, stop: asyncio.Event) -> None:
            started.set()
            await stop.wait()
            stopped.set()

    monkeypatch.setattr(settings, "RUN_JOBS_IN_WEB", True)
    monkeypatch.setattr(settings, "CHECK_MIGRATIONS_ON_STARTUP", False)
    monkeypatch.setattr(main, "JobRunner", FakeRunner)
    async with main.lifespan(main.app):
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not stopped.is_set()
    assert stopped.is_set()


async def test_without_the_setting_the_web_process_runs_no_jobs(monkeypatch):
    created = []
    monkeypatch.setattr(settings, "RUN_JOBS_IN_WEB", False)
    monkeypatch.setattr(settings, "CHECK_MIGRATIONS_ON_STARTUP", False)
    monkeypatch.setattr(main, "JobRunner", lambda **kwargs: created.append(kwargs))
    async with main.lifespan(main.app):
        pass
    assert created == []
