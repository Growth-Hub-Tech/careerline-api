"""Day 5: background jobs that are never lost and never run twice.

The queue is a Postgres table (background_jobs). A job is claimed with
SELECT ... FOR UPDATE SKIP LOCKED and a lease: if the worker dies, the lease runs out and another
worker picks the job up again (never lost). A dedupe key makes enqueuing the same job twice a
no-op, a claimed job is invisible to other workers, and the handler's database writes commit in
the same transaction that marks the job done (never run twice).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.jobs import queue, registry
from app.jobs.runner import JobRunner


@pytest.fixture
def calls(monkeypatch):
    """Registers test handlers for this test only; returns what they saw."""
    seen: list = []
    handlers = dict(registry.HANDLERS)
    monkeypatch.setattr(registry, "HANDLERS", handlers)

    async def record(session, payload):
        seen.append(payload["n"])
        await session.execute(
            text("INSERT INTO contact_messages_probe (n) VALUES (:n)"), {"n": payload["n"]}
        )

    async def boom(session, payload):
        seen.append(("boom", payload.get("n")))
        raise RuntimeError("the email provider is down")

    async def slow(session, payload):
        seen.append(("slow", payload["n"]))
        await asyncio.sleep(0.05)

    handlers["test.record"] = record
    handlers["test.boom"] = boom
    handlers["test.slow"] = slow
    return seen


@pytest.fixture(autouse=True)
def probe_table(database):
    with database.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS contact_messages_probe (n int)"))
        conn.execute(text("TRUNCATE contact_messages_probe"))
    yield
    with database.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS contact_messages_probe"))


async def enqueue(kind: str, payload: dict, **kwargs) -> int:
    async with AsyncSessionLocal() as session:
        job_id = await queue.enqueue(session, kind, payload, **kwargs)
        await session.commit()
    return job_id


def job_row(db, job_id: int):
    return db.execute(text("SELECT * FROM background_jobs WHERE id = :id"), {"id": job_id}).one()


def runner(name: str = "w1", **kwargs) -> JobRunner:
    kwargs.setdefault("lease_seconds", 30)
    kwargs.setdefault("retry_base_seconds", 60)
    return JobRunner(worker_id=name, **kwargs)


async def test_a_job_runs_once_and_is_marked_done(db, calls):
    job_id = await enqueue("test.record", {"n": 1})
    assert job_row(db, job_id).status == "queued"

    assert await runner().run_once() == 1
    assert await runner().run_once() == 0  # nothing left

    row = job_row(db, job_id)
    assert row.status == "succeeded"
    assert row.attempts == 1
    assert row.finished_at is not None
    assert calls == [1]
    assert db.execute(text("SELECT count(*) FROM contact_messages_probe")).scalar() == 1


async def test_enqueuing_the_same_job_twice_creates_one_job(db, calls):
    first = await enqueue("test.record", {"n": 7}, dedupe_key="welcome-email:learner:7")
    second = await enqueue("test.record", {"n": 7}, dedupe_key="welcome-email:learner:7")
    assert first == second
    assert db.execute(text("SELECT count(*) FROM background_jobs")).scalar() == 1

    await runner().run_once()
    # Even after it ran, the same key does not run it again
    assert await enqueue("test.record", {"n": 7}, dedupe_key="welcome-email:learner:7") == first
    await runner().run_once()
    assert calls == [7]


async def test_a_job_enqueued_in_a_rolled_back_transaction_does_not_exist(db, calls):
    async with AsyncSessionLocal() as session:
        await queue.enqueue(session, "test.record", {"n": 1})
        await session.rollback()
    assert await runner().run_once() == 0
    assert db.execute(text("SELECT count(*) FROM background_jobs")).scalar() == 0


async def test_a_failing_job_is_retried_later_then_dead_lettered(db, calls):
    job_id = await enqueue("test.boom", {"n": 1}, max_attempts=3)

    await runner().run_once()
    row = job_row(db, job_id)
    assert row.status == "queued"
    assert row.attempts == 1
    assert "the email provider is down" in row.last_error
    assert row.run_after > datetime.now(UTC) + timedelta(seconds=30)  # backoff
    assert await runner().run_once() == 0  # not before its retry time

    for attempt in (2, 3):
        db.execute(
            text("UPDATE background_jobs SET run_after = now() WHERE id = :id"), {"id": job_id}
        )
        db.commit()
        await runner().run_once()
        assert job_row(db, job_id).attempts == attempt

    row = job_row(db, job_id)
    assert row.status == "dead"
    assert row.finished_at is not None
    db.execute(text("UPDATE background_jobs SET run_after = now() WHERE id = :id"), {"id": job_id})
    db.commit()
    assert await runner().run_once() == 0  # a dead job never runs again on its own
    assert len(calls) == 3


async def test_the_backoff_grows_with_each_attempt():
    r = runner(retry_base_seconds=10, retry_max_seconds=100)
    assert [r.backoff_seconds(n) for n in (1, 2, 3, 4, 5, 6)] == [10, 20, 40, 80, 100, 100]


async def test_a_job_whose_worker_died_is_picked_up_again(db, calls):
    job_id = await enqueue("test.record", {"n": 5})
    # Worker 1 claims it, then "crashes" (never finishes it)
    async with AsyncSessionLocal() as session:
        claimed = await queue.claim(session, "crashed-worker", limit=1, lease_seconds=30)
        await session.commit()
    assert [job.id for job in claimed] == [job_id]
    assert job_row(db, job_id).status == "running"

    # While the lease is valid, nobody else takes it
    assert await runner("w2").run_once() == 0

    # The lease runs out: another worker takes it and finishes it
    db.execute(
        text(
            "UPDATE background_jobs SET locked_until = now() - interval '1 second' WHERE id = :id"
        ),
        {"id": job_id},
    )
    db.commit()
    assert await runner("w2").run_once() == 1
    row = job_row(db, job_id)
    assert row.status == "succeeded"
    assert row.attempts == 2
    assert calls == [5]


async def test_a_worker_that_lost_its_lease_cannot_finish_the_job(db, calls, monkeypatch):
    job_id = await enqueue("test.record", {"n": 9})

    async def stolen(session, payload):
        # While this worker runs, its lease ran out and another worker claimed the job
        with_db = db.execute(
            text("UPDATE background_jobs SET locked_by = 'other-worker' WHERE id = :id"),
            {"id": job_id},
        )
        assert with_db.rowcount == 1
        db.commit()
        await session.execute(text("INSERT INTO contact_messages_probe (n) VALUES (9)"))

    monkeypatch.setitem(registry.HANDLERS, "test.record", stolen)
    await runner("w1").run_once()

    # Its database writes were rolled back and the job stays with the other worker
    assert db.execute(text("SELECT count(*) FROM contact_messages_probe")).scalar() == 0
    row = job_row(db, job_id)
    assert row.status == "running"
    assert row.locked_by == "other-worker"


async def test_two_workers_never_run_the_same_job(db, calls):
    for n in range(30):
        await enqueue("test.slow", {"n": n})

    async def drain(name: str):
        r = runner(name, batch_size=3)
        while await r.run_once():
            pass

    await asyncio.gather(drain("w1"), drain("w2"), drain("w3"))
    numbers = [n for _, n in calls]
    assert sorted(numbers) == list(range(30))  # every job ran exactly once
    statuses = db.execute(
        text("SELECT status, count(*) FROM background_jobs GROUP BY status")
    ).all()
    assert dict(statuses) == {"succeeded": 30}


async def test_a_job_of_unknown_kind_is_dead_lettered_at_once(db, calls):
    job_id = await enqueue("test.nobody-handles-this", {})
    await runner().run_once()
    row = job_row(db, job_id)
    assert row.status == "dead"
    assert "no handler" in row.last_error


async def test_a_job_that_runs_too_long_is_stopped_and_retried(db, calls, monkeypatch):
    async def hangs(session, payload):
        await asyncio.sleep(10)

    monkeypatch.setitem(registry.HANDLERS, "test.record", hangs)
    job_id = await enqueue("test.record", {"n": 1})
    await runner(timeout_seconds=0.1).run_once()
    row = job_row(db, job_id)
    assert row.status == "queued"
    assert "timed out" in row.last_error


async def test_the_worker_loop_runs_jobs_until_stopped(db, calls):
    await enqueue("test.record", {"n": 1})
    await enqueue("test.record", {"n": 2})
    stop = asyncio.Event()
    task = asyncio.create_task(runner(poll_seconds=0.01).run_forever(stop))
    for _ in range(200):
        if len(calls) == 2:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert sorted(calls) == [1, 2]


async def test_a_job_whose_batch_lease_ran_out_is_not_run_by_two_workers(db, calls):
    """A claims 3 jobs in one batch and runs them one by one. Job 3 starts after the batch lease
    ran out, so B may take it over, but then A must skip it, never run it as well."""

    async def one_second(session, payload):
        calls.append(("run", payload["n"]))
        await asyncio.sleep(1.0)

    registry.HANDLERS["test.one_second"] = one_second
    for n in (1, 2, 3):
        await enqueue("test.one_second", {"n": n})

    a = runner("A", lease_seconds=1.5, batch_size=3)  # timeout 1.2s > 1.0s per job
    b = runner("B", lease_seconds=1.5, batch_size=3)

    async def b_polls_while_a_runs_job_2():
        await asyncio.sleep(1.75)  # job 2 started at 1.0s; the batch lease ended at 1.5s
        await b.run_once()

    await asyncio.gather(a.run_once(), b_polls_while_a_runs_job_2())

    assert sorted(calls) == [("run", 1), ("run", 2), ("run", 3)]  # each job ran once
    statuses = db.execute(text("SELECT status FROM background_jobs")).scalars().all()
    assert statuses == ["succeeded"] * 3
