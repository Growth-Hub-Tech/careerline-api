"""Day 19: recruiters, part 1: candidates and sending invitations.

An organisation's recruiters (and admins and owners) keep a list of candidates and invite them
to take a test from the catalogue. The invitee gets an email with the link (opening and accepting
it is Day 20). A candidate's status follows their invitations: added -> invited -> in_progress
-> completed. Everything is scoped to the caller's organisation.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope
from tests.integration.test_organisation_users import add_learner, headers_for

API = settings.API_PREFIX


def _org(db, name: str, person: str, role: str = "recruiter") -> dict:
    learner_id = add_learner(db, person)
    org_id = db.execute(
        text("INSERT INTO organisations (name) VALUES (:n) RETURNING id"), {"n": name}
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO organisation_members (organisation_id, learner_id, role) "
            "VALUES (:o, :l, :r)"
        ),
        {"o": org_id, "l": learner_id, "r": role},
    )
    db.commit()
    return {"id": org_id, "learner_id": learner_id, "headers": headers_for(db, learner_id)}


@pytest.fixture
def recruiter(db) -> dict:
    return _org(db, "Acme Recruiting", "rita")


@pytest.fixture
def rival(db) -> dict:
    return _org(db, "Rival Hiring", "rex", role="owner")


async def add_candidate(client, who, email="chidi@example.com", **extra):
    return await client.post(
        f"{API}/recruiter/candidates",
        headers=who["headers"],
        json={"full_name": "Chidi Okafor", "email": email, **extra},
    )


async def invite(client, who, skill, **extra):
    body = {
        "email": "chidi@example.com",
        "full_name": "Chidi Okafor",
        "test_id": 200 + skill["skill_id"],
    }
    return await client.post(f"{API}/invitations", headers=who["headers"], json={**body, **extra})


# ---------- candidates ----------


async def test_a_recruiter_adds_and_lists_candidates(client, recruiter):
    response = await add_candidate(client, recruiter, email="Chidi@Example.com")
    assert response.status_code == 201, response.text
    assert "X-Sample-Data" not in response.headers
    candidate = response.json()["data"]
    assert candidate["email"] == "chidi@example.com" and candidate["status"] == "added"
    assert candidate["role_id"] is None and candidate["latest_result"] is None

    await add_candidate(client, recruiter, email="ngozi@example.com")
    page = (await client.get(f"{API}/recruiter/candidates", headers=recruiter["headers"])).json()
    assert page["data"]["total"] == 2
    assert [c["email"] for c in page["data"]["items"]] == ["ngozi@example.com", "chidi@example.com"]
    one = await client.get(
        f"{API}/recruiter/candidates/{candidate['candidate_id']}", headers=recruiter["headers"]
    )
    assert one.json()["data"]["full_name"] == "Chidi Okafor"


async def test_the_same_email_twice_is_a_409(client, recruiter):
    await add_candidate(client, recruiter)
    response = await add_candidate(client, recruiter, email="CHIDI@example.com")
    assert_error_envelope(response, 409, "conflict")


async def test_an_unknown_role_is_a_404(client, recruiter):
    assert_error_envelope(await add_candidate(client, recruiter, role_id=9999), 404, "not_found")


async def test_candidates_belong_to_one_organisation(client, recruiter, rival):
    candidate = (await add_candidate(client, recruiter)).json()["data"]
    theirs = await client.get(f"{API}/recruiter/candidates", headers=rival["headers"])
    assert theirs.json()["data"]["total"] == 0
    response = await client.get(
        f"{API}/recruiter/candidates/{candidate['candidate_id']}", headers=rival["headers"]
    )
    assert_error_envelope(response, 404, "not_found")
    assert (await add_candidate(client, rival)).status_code == 201  # their own list


async def test_a_learner_without_an_organisation_is_refused(client, learner):
    response = await client.get(f"{API}/recruiter/candidates", headers=learner["headers"])
    assert_error_envelope(response, 403, "forbidden")


# ---------- sending invitations ----------


async def test_an_invitation_is_sent_by_email_and_adds_the_candidate(client, recruiter, skill, db):
    response = await invite(client, recruiter, skill, message="Looking forward to it")
    assert response.status_code == 201, response.text
    sent = response.json()["data"]
    assert sent["status"] == "sent" and sent["kind"] == "candidate"
    assert sent["test_id"] == 200 + skill["skill_id"] and sent["test_title"] == "Python"
    assert sent["invite_url"] == f"{settings.FRONTEND_URL.rstrip('/')}/invite/{sent['token']}"
    assert sent["organisation_id"] == recruiter["id"] and sent["candidate_id"]
    expires = datetime.fromisoformat(sent["expires_at"]) - datetime.fromisoformat(sent["sent_at"])
    assert timedelta(days=6, hours=23) < expires <= timedelta(days=7, minutes=1)

    candidate = (
        await client.get(
            f"{API}/recruiter/candidates/{sent['candidate_id']}", headers=recruiter["headers"]
        )
    ).json()["data"]
    assert candidate["status"] == "invited" and candidate["email"] == "chidi@example.com"

    subject, body = db.execute(
        text(
            "SELECT subject, text_body FROM email_outbox WHERE template = 'invitation' "
            "AND to_email = 'chidi@example.com'"
        )
    ).one()
    assert "Acme Recruiting" in subject
    assert sent["invite_url"] in body and "Looking forward to it" in body


async def test_inviting_a_known_candidate_reuses_them(client, recruiter, skill):
    candidate = (await add_candidate(client, recruiter)).json()["data"]
    sent = (await invite(client, recruiter, skill, candidate_id=candidate["candidate_id"])).json()[
        "data"
    ]
    assert sent["candidate_id"] == candidate["candidate_id"]
    by_email = (await invite(client, recruiter, skill)).json()["data"]
    assert by_email["candidate_id"] == candidate["candidate_id"]
    page = (await client.get(f"{API}/recruiter/candidates", headers=recruiter["headers"])).json()
    assert page["data"]["total"] == 1


async def test_bad_invitations_are_refused(client, recruiter, rival, skill):
    assert_error_envelope(await invite(client, recruiter, skill, test_id=999), 404, "not_found")
    theirs = (await add_candidate(client, rival)).json()["data"]
    response = await invite(client, recruiter, skill, candidate_id=theirs["candidate_id"])
    assert_error_envelope(response, 404, "not_found")
    response = await invite(client, recruiter, skill, organisation_id=rival["id"])
    assert_error_envelope(response, 404, "not_found")


async def test_sent_invitations_are_listed_newest_first_and_kept_private(
    client, recruiter, rival, skill
):
    first = (await invite(client, recruiter, skill)).json()["data"]
    second = (await invite(client, recruiter, skill, email="ngozi@example.com")).json()["data"]
    page = (await client.get(f"{API}/invitations", headers=recruiter["headers"])).json()["data"]
    assert [i["invitation_id"] for i in page["items"]] == [
        second["invitation_id"],
        first["invitation_id"],
    ]
    one = await client.get(
        f"{API}/invitations/{first['invitation_id']}", headers=recruiter["headers"]
    )
    assert one.json()["data"]["token"] == first["token"]
    assert (await client.get(f"{API}/invitations", headers=rival["headers"])).json()["data"][
        "total"
    ] == 0
    hidden = await client.get(
        f"{API}/invitations/{first['invitation_id']}", headers=rival["headers"]
    )
    assert_error_envelope(hidden, 404, "not_found")


async def test_revoking_an_invitation(client, recruiter, skill):
    sent = (await invite(client, recruiter, skill)).json()["data"]
    path = f"{API}/invitations/{sent['invitation_id']}/revoke"
    revoked = await client.post(path, headers=recruiter["headers"])
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "revoked"
    assert (await client.post(path, headers=recruiter["headers"])).json()["data"]["status"] == (
        "revoked"
    )
    candidate = (
        await client.get(
            f"{API}/recruiter/candidates/{sent['candidate_id']}", headers=recruiter["headers"]
        )
    ).json()["data"]
    assert candidate["status"] == "added"


async def test_an_old_invitation_shows_as_expired(client, recruiter, skill, database):
    sent = (await invite(client, recruiter, skill)).json()["data"]
    with database.begin() as conn:
        conn.execute(
            text("UPDATE invitations SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(minutes=1), "id": sent["invitation_id"]},
        )
    shown = await client.get(
        f"{API}/invitations/{sent['invitation_id']}", headers=recruiter["headers"]
    )
    assert shown.json()["data"]["status"] == "expired"
    revoke = await client.post(
        f"{API}/invitations/{sent['invitation_id']}/revoke", headers=recruiter["headers"]
    )
    assert_error_envelope(revoke, 409, "conflict")


async def test_candidates_filter_by_status(client, recruiter, skill):
    await add_candidate(client, recruiter, email="ngozi@example.com")
    await invite(client, recruiter, skill)
    invited = await client.get(
        f"{API}/recruiter/candidates", headers=recruiter["headers"], params={"status": "invited"}
    )
    assert [c["email"] for c in invited.json()["data"]["items"]] == ["chidi@example.com"]
