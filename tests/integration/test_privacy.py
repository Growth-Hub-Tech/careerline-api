"""Day 18: privacy (NDPR / GDPR). Consents are real and every change is kept; a person can get a
copy of everything held about them (made in the background, downloaded through a short signed
link); and deleting an account needs the password, waits 30 days so it can be cancelled, then
erases the person's data and leaves only anonymous test statistics and payment records."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import PASSWORD, assert_error_envelope, login, take_test

API = settings.API_PREFIX


async def run_jobs() -> None:
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


def _path(url: str) -> str:
    return urlparse(url).path


# ---------- consents ----------


async def test_consents_start_off_and_every_change_is_kept(client, learner, db):
    response = await client.get(f"{API}/privacy/consents", headers=learner["headers"])
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    items = response.json()["data"]["items"]
    assert [(c["key"], c["granted"]) for c in items] == [
        ("marketing_emails", False),
        ("share_profile_with_recruiters", False),
        ("product_research", False),
    ]

    changed = await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "share_profile_with_recruiters", "granted": True}]},
    )
    assert changed.status_code == 200, changed.text
    by_key = {c["key"]: c for c in changed.json()["data"]["items"]}
    assert by_key["share_profile_with_recruiters"]["granted"] is True
    assert by_key["marketing_emails"]["granted"] is False

    await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "share_profile_with_recruiters", "granted": False}]},
    )
    history = db.execute(
        text("SELECT key, granted FROM consent_events WHERE learner_id = :l ORDER BY id"),
        {"l": learner["learner_id"]},
    ).all()
    assert history == [
        ("share_profile_with_recruiters", True),
        ("share_profile_with_recruiters", False),
    ]


async def test_setting_a_consent_to_what_it_is_records_nothing(client, learner, db):
    body = {"items": [{"key": "marketing_emails", "granted": False}]}
    response = await client.put(f"{API}/privacy/consents", headers=learner["headers"], json=body)
    assert response.status_code == 200
    assert db.execute(text("SELECT count(*) FROM consent_events")).scalar() == 0


async def test_consents_are_per_person_and_checked(client, learner, other_learner):
    await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "product_research", "granted": True}]},
    )
    theirs = (await client.get(f"{API}/privacy/consents", headers=other_learner["headers"])).json()
    assert all(c["granted"] is False for c in theirs["data"]["items"])
    bad = await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "sell_my_data", "granted": True}]},
    )
    assert_error_envelope(bad, 422, "validation_error")
    assert_error_envelope(await client.get(f"{API}/privacy/consents"), 401, "unauthenticated")


# ---------- a copy of my data ----------


async def test_a_data_export_is_made_in_the_background_and_downloaded(client, learner, skill):
    await take_test(client, learner["headers"], skill)
    await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "marketing_emails", "granted": True}]},
    )
    response = await client.post(f"{API}/privacy/data-exports", headers=learner["headers"])
    assert response.status_code == 202, response.text
    queued = response.json()["data"]
    assert queued["status"] == "queued" and queued["download_url"] is None

    again = await client.post(f"{API}/privacy/data-exports", headers=learner["headers"])
    assert again.json()["data"]["export_id"] == queued["export_id"]  # one at a time

    await run_jobs()
    ready = (
        await client.get(
            f"{API}/privacy/data-exports/{queued['export_id']}", headers=learner["headers"]
        )
    ).json()["data"]
    assert ready["status"] == "ready" and ready["download_url"] and ready["expires_at"]

    download = await client.get(_path(ready["download_url"]))  # no login: the link is the proof
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/json")
    assert "attachment" in download.headers["content-disposition"]
    data = json.loads(download.content)
    assert data["account"]["email"] == learner["email"]
    assert data["account"]["full_name"] == "Ada Learner"
    assert "hashed_password" not in json.dumps(data)
    assert len(data["tests"]) == 1 and data["tests"][0]["answers"]
    assert data["tests"][0]["result"]["level"]
    consents = {c["key"]: c["granted"] for c in data["consents"]}
    assert consents["marketing_emails"] is True
    for section in ("payments", "credit_transactions", "skill_history", "beginner_intakes"):
        assert section in data


async def test_the_ready_email_points_at_the_website(client, learner, db):
    await client.post(f"{API}/privacy/data-exports", headers=learner["headers"])
    runner = JobRunner(worker_id="test")  # stop before the email is sent (sending empties it)
    while db.execute(text("SELECT status FROM data_exports")).scalar() != "ready":
        assert await runner.run_once()
        db.rollback()
    (subject, body) = db.execute(
        text(
            "SELECT subject, text_body FROM email_outbox WHERE template = 'data_export_ready' "
            "AND to_email = :e"
        ),
        {"e": learner["email"]},
    ).one()
    assert "ready" in subject.lower()
    assert settings.FRONTEND_URL in body and "/data-exports/" not in body


async def test_someone_elses_export_is_a_404(client, learner, other_learner):
    queued = (await client.post(f"{API}/privacy/data-exports", headers=learner["headers"])).json()
    response = await client.get(
        f"{API}/privacy/data-exports/{queued['data']['export_id']}",
        headers=other_learner["headers"],
    )
    assert_error_envelope(response, 404, "not_found")


async def test_an_old_export_or_a_bad_link_is_410(client, learner, database):
    queued = (await client.post(f"{API}/privacy/data-exports", headers=learner["headers"])).json()
    export_id = queued["data"]["export_id"]
    await run_jobs()
    ready = (
        await client.get(f"{API}/privacy/data-exports/{export_id}", headers=learner["headers"])
    ).json()["data"]
    with database.begin() as conn:
        conn.execute(
            text("UPDATE data_exports SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "id": export_id},
        )
    response = await client.get(
        f"{API}/privacy/data-exports/{export_id}", headers=learner["headers"]
    )
    assert_error_envelope(response, 410, "expired")
    assert_error_envelope(await client.get(_path(ready["download_url"])), 410, "expired")
    bad = await client.get(f"{API}/privacy/data-exports/download/not-a-token")
    assert_error_envelope(bad, 410, "expired")
    # a new one can be asked for
    fresh = await client.post(f"{API}/privacy/data-exports", headers=learner["headers"])
    assert fresh.json()["data"]["export_id"] != export_id


# ---------- deleting my account ----------


async def _ask_deletion(client, learner, password=PASSWORD):
    return await client.post(
        f"{API}/privacy/account-deletion",
        headers=learner["headers"],
        json={"password": password, "reason": "Not using it"},
    )


async def test_deletion_needs_the_password(client, learner):
    response = await _ask_deletion(client, learner, password="wrong-password-here")
    assert_error_envelope(response, 400, "wrong_password")


async def test_deletion_is_scheduled_30_days_ahead_and_can_be_cancelled(client, learner, db):
    response = await _ask_deletion(client, learner)
    assert response.status_code == 202, response.text
    scheduled = response.json()["data"]
    assert scheduled["status"] == "scheduled"
    requested = datetime.fromisoformat(scheduled["requested_at"])
    planned = datetime.fromisoformat(scheduled["scheduled_for"])
    assert timedelta(days=29, hours=23) < planned - requested <= timedelta(days=30, minutes=1)
    status = await client.get(f"{API}/privacy/account-deletion", headers=learner["headers"])
    assert status.json()["data"]["status"] == "scheduled"
    assert (
        db.execute(
            text("SELECT count(*) FROM email_outbox WHERE template = 'account_deletion_scheduled'")
        ).scalar()
        == 1
    )

    cancelled = await client.delete(f"{API}/privacy/account-deletion", headers=learner["headers"])
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"] == {
        "status": "cancelled",
        "requested_at": scheduled["requested_at"],
        "scheduled_for": None,
    }
    again = await client.delete(f"{API}/privacy/account-deletion", headers=learner["headers"])
    assert_error_envelope(again, 404, "not_found")


async def test_without_a_request_there_is_nothing_to_show_or_cancel(client, learner):
    response = await client.get(f"{API}/privacy/account-deletion", headers=learner["headers"])
    assert_error_envelope(response, 404, "not_found")
    response = await client.delete(f"{API}/privacy/account-deletion", headers=learner["headers"])
    assert_error_envelope(response, 404, "not_found")


async def _make_due(database, learner) -> None:
    with database.begin() as conn:
        conn.execute(
            text(
                "UPDATE account_deletions SET scheduled_for = now() - interval '1 minute' "
                "WHERE learner_id = :l"
            ),
            {"l": learner["learner_id"]},
        )
        conn.execute(
            text(
                "UPDATE background_jobs SET run_after = now() - interval '1 minute' "
                "WHERE kind = 'privacy.erase_account'"
            )
        )


async def test_a_due_deletion_erases_the_person_and_keeps_anonymous_records(
    client, learner, other_learner, skill, database, db
):
    await take_test(client, learner["headers"], skill)
    await take_test(client, other_learner["headers"], skill)
    await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "marketing_emails", "granted": True}]},
    )
    await _ask_deletion(client, learner)
    await run_jobs()  # too early: nothing happens
    assert (
        db.execute(
            text("SELECT email FROM learner WHERE learner_id = :l"), {"l": learner["learner_id"]}
        ).scalar()
        == learner["email"]
    )

    await _make_due(database, learner)
    await run_jobs()

    row = db.execute(
        text(
            "SELECT full_name, email, phone_number, hashed_password, learner_status::text "
            "FROM learner WHERE learner_id = :l"
        ),
        {"l": learner["learner_id"]},
    ).one()
    assert row[0] == "Deleted account" and row[1].endswith("@deleted.invalid")
    assert row[2] is None and row[3] is None and row[4] == "INACTIVE"
    for table in ("auth_sessions", "learner_consents", "consent_events", "beginner_intakes"):
        count = db.execute(
            text(f"SELECT count(*) FROM {table} WHERE learner_id = :l"),
            {"l": learner["learner_id"]},
        ).scalar()
        assert count == 0, table
    assert (
        db.execute(
            text("SELECT count(*) FROM email_outbox WHERE to_email = :e"), {"e": learner["email"]}
        ).scalar()
        == 0
    )
    # the test result stays, anonymous, so other people's percentiles do not change
    assert (
        db.execute(
            text("SELECT count(*) FROM test_attempt WHERE learner_id = :l"),
            {"l": learner["learner_id"]},
        ).scalar()
        == 1
    )
    status = db.execute(
        text("SELECT status FROM account_deletions WHERE learner_id = :l"),
        {"l": learner["learner_id"]},
    ).scalar()
    assert status == "completed"
    # the old token and password no longer work; the other person is untouched
    me = await client.get(f"{API}/accounts/me", headers=learner["headers"])
    assert_error_envelope(me, 401, "unauthenticated")
    assert (await login(client, learner["email"])).status_code == 401
    theirs = await client.get(f"{API}/accounts/me", headers=other_learner["headers"])
    assert theirs.status_code == 200


async def test_a_cancelled_deletion_is_never_carried_out(client, learner, database, db):
    await _ask_deletion(client, learner)
    await client.delete(f"{API}/privacy/account-deletion", headers=learner["headers"])
    await _make_due(database, learner)
    await run_jobs()
    assert (
        db.execute(
            text("SELECT email FROM learner WHERE learner_id = :l"), {"l": learner["learner_id"]}
        ).scalar()
        == learner["email"]
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/privacy/data-exports"),
        ("GET", "/privacy/data-exports/1"),
        ("POST", "/privacy/account-deletion"),
        ("GET", "/privacy/account-deletion"),
        ("DELETE", "/privacy/account-deletion"),
    ],
)
async def test_privacy_needs_a_login(client, method, path):
    response = await client.request(method, f"{API}{path}", json={"password": "x"})
    assert_error_envelope(response, 401, "unauthenticated")
