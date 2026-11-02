"""Day 19: the invitee's side of an invitation. The link is public (the page can show who invited
them), accepting needs a signed-in account and starts the invited test, free of charge."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope
from tests.integration.test_recruiter import invite, recruiter  # noqa: F401

API = settings.API_PREFIX


async def _sent(client, recruiter, skill, database=None, **extra) -> dict:  # noqa: F811
    with database.begin() as conn:
        conn.execute(
            text("INSERT INTO test_prices (skill_id, price_credits) VALUES (:s, 2)"),
            {"s": skill["skill_id"]},
        )
    return (await invite(client, recruiter, skill, message="See you", **extra)).json()["data"]


async def test_the_link_shows_who_invited_them(client, recruiter, skill, database):  # noqa: F811
    sent = await _sent(client, recruiter, skill, database)
    response = await client.get(f"{API}/invitations/token/{sent['token']}")
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    assert response.json()["data"] == {
        "token": sent["token"],
        "status": "sent",
        "invited_by": "Acme Recruiting",
        "full_name": "Chidi Okafor",
        "test_id": sent["test_id"],
        "test_title": "Python",
        "duration_minutes": settings.ATTEMPT_TIME_LIMIT_MINUTES,
        "message": "See you",
        "expires_at": sent["expires_at"],
        "attempt_id": None,
    }
    assert_error_envelope(await client.get(f"{API}/invitations/token/nope"), 404, "not_found")


async def test_accepting_starts_the_test_for_free(client, recruiter, learner, skill, database, db):  # noqa: F811
    sent = await _sent(client, recruiter, skill, database)
    path = f"{API}/invitations/token/{sent['token']}/accept"
    response = await client.post(path, headers=learner["headers"])
    assert response.status_code == 200, response.text
    accepted = response.json()["data"]
    assert accepted["status"] == "accepted" and accepted["attempt_id"]
    again = await client.post(path, headers=learner["headers"])  # accepting twice is fine
    assert again.json()["data"]["attempt_id"] == accepted["attempt_id"]
    question = await client.get(
        f"{API}/attempts/{accepted['attempt_id']}/question", headers=learner["headers"]
    )
    assert question.status_code == 200
    credits = (await client.get(f"{API}/credits", headers=learner["headers"])).json()["data"]
    assert credits["transactions"] == []  # the organisation's invitation: no credits taken
    shown = await client.get(
        f"{API}/invitations/{sent['invitation_id']}", headers=recruiter["headers"]
    )
    assert shown.json()["data"]["status"] == "accepted"
    candidate = await client.get(
        f"{API}/recruiter/candidates/{sent['candidate_id']}", headers=recruiter["headers"]
    )
    assert candidate.json()["data"]["status"] == "in_progress"


async def test_someone_else_cannot_accept_an_accepted_invitation(
    client,
    recruiter,  # noqa: F811
    learner,
    other_learner,
    skill,
    database,
):
    sent = await _sent(client, recruiter, skill, database)
    path = f"{API}/invitations/token/{sent['token']}/accept"
    await client.post(path, headers=learner["headers"])
    assert_error_envelope(
        await client.post(path, headers=other_learner["headers"]), 409, "conflict"
    )


async def test_revoked_and_expired_invitations_cannot_be_accepted(
    client,
    recruiter,  # noqa: F811
    learner,
    skill,
    database,
):
    revoked = await _sent(client, recruiter, skill, database)
    await client.post(
        f"{API}/invitations/{revoked['invitation_id']}/revoke", headers=recruiter["headers"]
    )
    response = await client.post(
        f"{API}/invitations/token/{revoked['token']}/accept", headers=learner["headers"]
    )
    assert_error_envelope(response, 409, "conflict")

    old = (await invite(client, recruiter, skill, email="ngozi@example.com")).json()["data"]
    with database.begin() as conn:
        conn.execute(
            text("UPDATE invitations SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "id": old["invitation_id"]},
        )
    assert_error_envelope(
        await client.get(f"{API}/invitations/token/{old['token']}"), 410, "expired"
    )
    response = await client.post(
        f"{API}/invitations/token/{old['token']}/accept", headers=learner["headers"]
    )
    assert_error_envelope(response, 410, "expired")


async def test_accepting_needs_a_login(client, recruiter, skill, database):  # noqa: F811
    sent = await _sent(client, recruiter, skill, database)
    response = await client.post(f"{API}/invitations/token/{sent['token']}/accept")
    assert_error_envelope(response, 401, "unauthenticated")
