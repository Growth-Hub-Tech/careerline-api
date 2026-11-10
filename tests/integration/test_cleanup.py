"""Daily housekeeping: finished jobs, sent emails and expired sessions older than 30 days go."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.jobs import cleanup
from app.jobs.runner import JobRunner

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=31)
YOUNG = NOW - timedelta(days=29)
TODAY = NOW.date()


def _job(db, status: str, finished_at=None, run_after=None, locked_until=None) -> int:
    row = db.execute(
        text(
            "INSERT INTO background_jobs (kind, status, finished_at, run_after, locked_until) "
            "VALUES ('probe', :status, :finished_at, COALESCE(:run_after, now()), :locked_until) "
            "RETURNING id"
        ),
        {
            "status": status,
            "finished_at": finished_at,
            "run_after": run_after,
            "locked_until": locked_until,
        },
    ).scalar_one()
    db.commit()
    return row


def _email(db, status: str, sent_at=None) -> int:
    row = db.execute(
        text(
            "INSERT INTO email_outbox (to_email, template, subject, status, sent_at) "
            "VALUES ('ada@example.com', 'probe', 'Hello', :status, :sent_at) RETURNING id"
        ),
        {"status": status, "sent_at": sent_at},
    ).scalar_one()
    db.commit()
    return row


def _session(db, learner_id: int, expires_at) -> uuid.UUID:
    session_id = uuid.uuid4()
    db.execute(
        text("INSERT INTO auth_sessions (id, learner_id, expires_at) VALUES (:id, :l, :e)"),
        {"id": session_id, "l": learner_id, "e": expires_at},
    )
    db.commit()
    return session_id


def _ids(db, table: str) -> set:
    return set(db.execute(text(f"SELECT id FROM {table}")).scalars())


async def _run_cleanup(day) -> None:
    async with AsyncSessionLocal() as session:
        await cleanup.cleanup(session, {"date": day.isoformat()})
        await session.commit()


def _cleanup_jobs(db) -> list:
    return db.execute(
        text("SELECT dedupe_key, run_after FROM background_jobs WHERE kind = 'cleanup' ORDER BY id")
    ).all()


async def test_old_finished_rows_go_and_everything_else_stays(db, learner):
    gone_jobs = {_job(db, "succeeded", OLD), _job(db, "dead", OLD)}
    kept_jobs = {
        _job(db, "succeeded", YOUNG),
        _job(db, "queued", run_after=NOW + timedelta(days=1)),
        _job(db, "running", locked_until=NOW + timedelta(hours=1)),
    }
    gone_emails = {_email(db, "sent", OLD)}
    kept_emails = {_email(db, "sent", YOUNG), _email(db, "queued")}
    gone_sessions = {_session(db, learner["learner_id"], OLD)}
    kept_sessions = {
        _session(db, learner["learner_id"], NOW - timedelta(days=1)),
        _session(db, learner["learner_id"], NOW + timedelta(days=1)),
    }

    await _run_cleanup(TODAY)

    jobs, emails, sessions = (
        _ids(db, t) for t in ("background_jobs", "email_outbox", "auth_sessions")
    )
    assert not gone_jobs & jobs and kept_jobs <= jobs
    assert not gone_emails & emails and kept_emails <= emails
    assert not gone_sessions & sessions and kept_sessions <= sessions


async def test_each_run_schedules_the_next_day_once(db):
    await _run_cleanup(TODAY)
    await _run_cleanup(TODAY)  # a repeat (a retry, say) adds nothing
    tomorrow = TODAY + timedelta(days=1)
    rows = _cleanup_jobs(db)
    assert [key for key, _ in rows] == [f"cleanup:{tomorrow.isoformat()}"]
    assert rows[0][1] == datetime.combine(tomorrow, cleanup.RUN_AT)


async def test_a_late_run_schedules_tomorrow_and_does_not_catch_up(db):
    await _run_cleanup(TODAY - timedelta(days=5))
    assert [key for key, _ in _cleanup_jobs(db)] == [
        f"cleanup:{(TODAY + timedelta(days=1)).isoformat()}"
    ]


async def test_starting_twice_schedules_one_cleanup_for_today(db):
    await cleanup.schedule_todays_cleanup()
    await cleanup.schedule_todays_cleanup()
    assert [key for key, _ in _cleanup_jobs(db)] == [f"cleanup:{TODAY.isoformat()}"]


async def test_a_failed_run_keeps_the_rows_and_schedules_nothing(db, monkeypatch):
    old_job = _job(db, "succeeded", OLD)
    await cleanup.schedule_todays_cleanup()

    async def broken(*args, **kwargs):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(cleanup, "schedule_cleanup", broken)
    await JobRunner(worker_id="test").run_once()

    assert old_job in _ids(db, "background_jobs")  # the deletes were rolled back with it
    status, error = db.execute(
        text("SELECT status, last_error FROM background_jobs WHERE kind = 'cleanup'")
    ).one()
    assert status == "queued" and "went away" in error  # retried later


async def test_a_cleanup_without_a_date_is_dead_not_retried(db):
    async with AsyncSessionLocal() as session:
        await cleanup.enqueue(session, cleanup.JOB_KIND, {}, dedupe_key="cleanup:broken")
        await session.commit()
    await JobRunner(worker_id="test").run_once()
    status = db.execute(
        text("SELECT status FROM background_jobs WHERE dedupe_key = 'cleanup:broken'")
    ).scalar_one()
    assert status == "dead"
