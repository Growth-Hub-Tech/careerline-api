"""Day 5: emails are sent by background jobs, exactly once, and land in the test mailbox on the
test server (EMAIL_BACKEND=test_mailbox), where Andrew's tests read them back."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.email import backends
from app.email.outbox import send_email
from app.jobs import registry
from app.jobs.runner import JobRunner
from app.main import create_app

API = settings.API_PREFIX
CONTEXT = {
    "ticket_id": "CT-20261027-0001",
    "full_name": "Ada Learner",
    "email": "ada@example.com",
    "topic": "support",
    "organisation": None,
    "message": "Please reset my password: https://example.com/help",
    "received_at": "27 Oct 2026, 10:00 UTC",
}


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "test_mailbox")
    monkeypatch.setattr(settings, "TEST_MAILBOX_TOKEN", "")


async def queue(to="ada@example.com", **kwargs) -> int:
    async with AsyncSessionLocal() as session:
        outbox_id = await send_email(
            session, to=to, template="contact_acknowledgement", context=CONTEXT, **kwargs
        )
        await session.commit()
    return outbox_id


async def drain():
    runner = JobRunner(worker_id="test", retry_base_seconds=60)
    while await runner.run_once():
        pass


async def test_send_email_queues_a_job_and_sends_nothing_yet(db):
    outbox_id = await queue()
    row = db.execute(text("SELECT * FROM email_outbox WHERE id = :id"), {"id": outbox_id}).one()
    assert row.status == "queued"
    assert row.to_email == "ada@example.com"
    jobs = db.execute(text("SELECT kind, payload FROM background_jobs")).all()
    assert [(j.kind, j.payload) for j in jobs] == [("send_email", {"outbox_id": outbox_id})]
    assert db.execute(text("SELECT count(*) FROM test_mailbox_messages")).scalar() == 0


async def test_the_job_delivers_it_to_the_test_mailbox_once(db):
    outbox_id = await queue()
    await drain()
    row = db.execute(text("SELECT * FROM email_outbox WHERE id = :id"), {"id": outbox_id}).one()
    assert row.status == "sent"
    assert row.sent_at is not None
    assert row.backend == "test_mailbox"
    # The bodies (they can hold sign-in links) are not kept once the email is sent
    assert row.html_body is None and row.text_body is None
    (mail,) = db.execute(text("SELECT * FROM test_mailbox_messages")).all()
    assert mail.to_email == "ada@example.com"
    assert "CT-20261027-0001" in mail.subject


async def test_a_retried_send_job_does_not_send_twice(db):
    outbox_id = await queue()
    await drain()
    # The worker died after sending but before the job was marked done: the job runs again
    async with AsyncSessionLocal() as session:
        await registry.HANDLERS["send_email"](session, {"outbox_id": outbox_id})
        await session.commit()
    assert db.execute(text("SELECT count(*) FROM test_mailbox_messages")).scalar() == 1


async def test_the_same_email_key_queues_one_email(db):
    first = await queue(dedupe_key="contact:CT-1:ack")
    second = await queue(dedupe_key="contact:CT-1:ack")
    assert first == second
    assert db.execute(text("SELECT count(*) FROM email_outbox")).scalar() == 1
    assert db.execute(text("SELECT count(*) FROM background_jobs")).scalar() == 1


async def test_a_failed_send_is_retried_later(db, monkeypatch):
    class Down:
        name = "smtp"

        async def send(self, message, *, session=None):
            raise ConnectionError("smtp server unreachable")

    monkeypatch.setattr(backends, "get_backend", lambda: Down())
    outbox_id = await queue()
    await drain()
    assert (
        db.execute(
            text("SELECT status FROM email_outbox WHERE id = :id"), {"id": outbox_id}
        ).scalar()
        == "queued"
    )
    job = db.execute(text("SELECT status, attempts, last_error FROM background_jobs")).one()
    assert (job.status, job.attempts) == ("queued", 1)
    assert "smtp server unreachable" in job.last_error


async def test_andrew_reads_the_test_mailbox_through_the_api(client, db):
    await queue(to="Ada@Example.com")
    await queue(to="someone-else@example.com")
    await drain()

    response = await client.get(f"{API}/test-mailbox", params={"to": "ada@example.com"})
    assert response.status_code == 200, response.text
    messages = response.json()["data"]["messages"]
    assert len(messages) == 1
    message = messages[0]
    assert message["to"] == "ada@example.com"
    assert "CT-20261027-0001" in message["subject"]
    assert message["text"] and message["html"]
    assert "https://example.com/help" in message["links"]

    response = await client.delete(f"{API}/test-mailbox", params={"to": "ada@example.com"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["deleted"] == 1
    response = await client.get(f"{API}/test-mailbox", params={"to": "ada@example.com"})
    assert response.json()["data"]["messages"] == []


async def test_the_test_mailbox_needs_the_token_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(settings, "TEST_MAILBOX_TOKEN", "letmein-not-a-real-token")
    response = await client.get(f"{API}/test-mailbox", params={"to": "ada@example.com"})
    assert response.status_code == 401
    response = await client.get(
        f"{API}/test-mailbox",
        params={"to": "ada@example.com"},
        headers={"X-Test-Mailbox-Token": "wrong"},
    )
    assert response.status_code == 401
    response = await client.get(
        f"{API}/test-mailbox",
        params={"to": "ada@example.com"},
        headers={"X-Test-Mailbox-Token": "letmein-not-a-real-token"},
    )
    assert response.status_code == 200


async def test_the_test_mailbox_is_off_when_emails_really_go_out(client, monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    response = await client.get(f"{API}/test-mailbox", params={"to": "ada@example.com"})
    assert response.status_code == 404


def test_production_has_no_test_mailbox(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SAMPLE_API_ENABLED", False)
    paths = {route.path for route in create_app().routes}
    assert f"{API}/test-mailbox" not in paths
