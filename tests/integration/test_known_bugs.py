"""Open bugs, written as tests of the CORRECT behaviour and marked xfail(strict=True).

Today each one fails, so pytest shows "xfailed" and the run stays green. When a later change
fixes the bug, the test passes, pytest reports "XPASS(strict)" and the run turns red: that is
the reminder to delete the xfail mark (and move the test next to its friends) so the fix stays
locked in.
"""

import time

import pytest
from sqlalchemy import text

import app.services.scoring_service as scoring_service
from app.core.config import settings
from tests.integration.conftest import (
    answers_for,
    assert_error_envelope,
    register,
    start_attempt,
    submit,
)

API = settings.API_PREFIX


@pytest.mark.xfail(
    strict=True,
    reason="Bug: POST /api/v1/auth/register accepts an empty or short password and an email "
    "that is not an email.",
)
@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("empty@example.com", ""),
        ("short@example.com", "1234567"),
        ("not-an-email", "long-enough-password"),
    ],
)
async def test_register_rejects_a_bad_email_or_weak_password(client, db, email, password):
    response = await register(client, email, password=password)

    assert_error_envelope(response, 422, "validation_error")
    created = db.execute(
        text("SELECT count(*) FROM learner WHERE email = :email"), {"email": email}
    ).scalar_one()
    assert created == 0


@pytest.mark.xfail(
    strict=True,
    reason="Bug: the old sign-up route POST /api/v1/learners/register creates accounts with "
    "no password. (The route itself is removed on Day 4.)",
)
async def test_old_signup_route_does_not_create_passwordless_accounts(client, db):
    response = await client.post(
        f"{API}/learners/register",
        json={"full_name": "No Password", "email": "nopass@example.com", "phone": "1"},
    )

    created = db.execute(
        text("SELECT count(*) FROM learner WHERE email = 'nopass@example.com'")
    ).scalar_one()
    assert created == 0, f"route answered {response.status_code} and created a learner"


@pytest.mark.xfail(
    strict=True,
    reason="Bug: the old sign-up route answers an existing email with that learner's id, "
    "without any login.",
)
async def test_old_signup_route_does_not_reveal_an_existing_learners_id(client, learner):
    response = await client.post(
        f"{API}/learners/register",
        json={"full_name": "Someone Else", "email": learner["email"], "phone": "1"},
    )

    assert response.status_code != 200
    assert str(learner["learner_id"]) not in str(response.json().get("data"))


@pytest.mark.xfail(
    strict=True,
    reason="Bug: submit calls OpenAI once per weak subskill, synchronously, inside the request "
    "(a blocking call in an async route, so the whole server waits). "
    "Day 5 moves the AI work to a background job.",
)
async def test_submit_does_not_wait_for_the_ai(client, learner, skill, monkeypatch):
    calls = []

    def slow_ai(skill_name, subskill_name, level_name, score):
        calls.append(subskill_name)
        time.sleep(1)  # pretend OpenAI is slow
        return "AI advice"

    # raising=False keeps this test meaningful after the old function is removed
    monkeypatch.setattr(scoring_service, "get_ai_benchmark", slow_ai, raising=False)
    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])

    started = time.monotonic()
    response = await submit(
        client, learner["headers"], attempt["attempt_id"], answers_for(attempt, skill, set())
    )
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert calls == [], f"submit called the AI {len(calls)} time(s) inside the request"
    assert elapsed < 1.0, f"submit took {elapsed:.1f}s waiting for the AI"


@pytest.mark.xfail(
    strict=True,
    reason="Bug: nothing creates the 4 proficiency levels, so on a fresh database every start "
    "attempt answers 400 'Level JUNIOR not found in database'. Day 4 adds seed files: then load "
    "them in clean_database (instead of inserting the levels by hand) and drop this xfail.",
)
async def test_a_fresh_database_can_start_an_attempt(client, learner, skill, database):
    with database.begin() as conn:
        # Back to what migrations alone give you: no levels
        conn.exec_driver_sql("TRUNCATE proficiency_level CASCADE")

    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": skill["skill_id"], "declared_level": "JUNIOR"},
    )

    assert response.status_code == 200, response.text
