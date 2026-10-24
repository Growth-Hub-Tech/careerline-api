"""Day 5: the contact form is real. Same path and answer as the sample one (POST /api/v1/contact,
201 {ticket_id, status, received_at}); it stores the message and emails the team and the sender
through background jobs. A spam trap field and a per-address limit keep bots out."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import assert_error_envelope

API = settings.API_PREFIX
FORM = {
    "full_name": "Ada Okafor",
    "email": "Ada@Example.com",
    "topic": "organisation_audit",
    "organisation": "Acme Ltd",
    "message": "We would like to audit our engineering team of 40 people.",
}


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "test_mailbox")
    monkeypatch.setattr(settings, "TEST_MAILBOX_TOKEN", "")
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "team@careerline.test")


async def drain():
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


async def inbox(client, address: str) -> list[dict]:
    response = await client.get(f"{API}/test-mailbox", params={"to": address})
    assert response.status_code == 200, response.text
    return response.json()["data"]["messages"]


async def test_the_contact_form_is_real_and_keeps_the_published_answer(client, db):
    response = await client.post(f"{API}/contact", json=FORM)
    assert response.status_code == 201, response.text
    assert "X-Sample-Data" not in response.headers
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert set(data) == {"ticket_id", "status", "received_at"}
    assert data["status"] == "received"
    assert data["ticket_id"].startswith("CT-")

    row = db.execute(text("SELECT * FROM contact_messages")).one()
    assert row.ticket_id == data["ticket_id"]
    assert row.email == "ada@example.com"
    assert row.topic == "organisation_audit"
    assert row.organisation == "Acme Ltd"


async def test_it_emails_the_team_and_thanks_the_sender(client):
    ticket = (await client.post(f"{API}/contact", json=FORM)).json()["data"]["ticket_id"]
    assert await inbox(client, "team@careerline.test") == []  # sent by a job, not the request
    await drain()

    (team,) = await inbox(client, "team@careerline.test")
    assert ticket in team["subject"]
    assert team["reply_to"] == "ada@example.com"  # the team answers the sender directly
    assert "We would like to audit our engineering team" in team["text"]

    (ack,) = await inbox(client, "ada@example.com")
    assert ticket in ack["subject"]
    assert "Ada Okafor" in ack["text"]


async def test_the_spam_trap_answers_normally_but_stores_and_sends_nothing(client, db):
    response = await client.post(f"{API}/contact", json={**FORM, "website": "http://spam.example"})
    assert response.status_code == 201, response.text
    assert response.json()["data"]["status"] == "received"
    await drain()
    assert db.execute(text("SELECT count(*) FROM contact_messages")).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM email_outbox")).scalar() == 0


async def test_one_address_can_send_5_messages_an_hour(client, db):
    for _ in range(5):
        response = await client.post(f"{API}/contact", json=FORM)
        assert response.status_code == 201, response.text
    response = await client.post(f"{API}/contact", json=FORM)
    assert_error_envelope(response, 429, "rate_limited")
    assert int(response.headers["Retry-After"]) > 0
    assert db.execute(text("SELECT count(*) FROM contact_messages")).scalar() == 5
    # The limit stores no IP address or email in clear
    buckets = db.execute(text("SELECT bucket FROM rate_limit_events")).scalars().all()
    assert buckets and not any("ada@example.com" in b or "127.0.0.1" in b for b in buckets)


async def test_the_form_is_validated(client):
    response = await client.post(f"{API}/contact", json={**FORM, "message": "hi"})
    error = assert_error_envelope(response, 422, "validation_error")
    assert error["details"][0]["loc"] == ["body", "message"]
    response = await client.post(f"{API}/contact", json={**FORM, "topic": "lottery"})
    assert_error_envelope(response, 422, "validation_error")


async def test_the_sample_contact_route_is_gone(client):
    from app.main import app

    contact = [
        route
        for route in app.routes
        if getattr(route, "path", "") == f"{API}/contact"
        and "POST" in getattr(route, "methods", ())
    ]
    assert len(contact) == 1
    assert not (contact[0].openapi_extra or {}).get("x-sample")
