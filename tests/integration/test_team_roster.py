"""Day 21: organisation audit part 1: the organisation and its team roster.

GET /organisations/me shows the caller's organisation and its seats. The roster
(GET/POST /organisations/{id}/members) is everyone the organisation will test, each mapped to a
job role: an upload adds new people and updates the ones already there (matched by email, any
case). More people than seats is a 402 and nothing is saved. A member's status follows their
team invitations (sent by an audit, Day 22): not_invited until then.
"""

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope
from tests.integration.test_recruiter import _org

API = settings.API_PREFIX


def add_role(db, slug: str, title: str, skills: list[tuple[int, str]] = ()) -> int:
    role_id = db.execute(
        text(
            "INSERT INTO job_roles (slug, title, track, summary, description) "
            "VALUES (:slug, :title, 'tech', 'x', 'x') RETURNING role_id"
        ),
        {"slug": slug, "title": title},
    ).scalar_one()
    for position, (skill_id, level) in enumerate(skills, start=1):
        db.execute(
            text(
                "INSERT INTO job_role_skills (role_id, skill_id, target_level, position) "
                "VALUES (:r, :s, :t, :p)"
            ),
            {"r": role_id, "s": skill_id, "t": level, "p": position},
        )
    db.commit()
    return role_id


@pytest.fixture
def owner(db) -> dict:
    return _org(db, "Acme Fintech", "olu", role="owner")


@pytest.fixture
def roles(db) -> dict:
    return {
        "frontend": add_role(db, "frontend-dev", "Frontend Developer"),
        "backend": add_role(db, "backend-dev", "Backend Developer"),
    }


def person(name: str, email: str, role_id: int, department: str | None = None) -> dict:
    return {"full_name": name, "email": email, "role_id": role_id, "department": department}


async def upload(client, who, members: list[dict]):
    return await client.post(
        f"{API}/organisations/{who['id']}/members", headers=who["headers"], json={"members": members}
    )


async def test_my_organisation_shows_its_seats(client, owner, roles):
    response = await client.get(f"{API}/organisations/me", headers=owner["headers"])
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    org = response.json()["data"]
    assert org["organisation_id"] == owner["id"] and org["name"] == "Acme Fintech"
    assert org["seats_total"] == 25 and org["seats_used"] == 0
    await upload(client, owner, [person("Ngozi Okeke", "ngozi@example.com", roles["backend"])])
    org = (await client.get(f"{API}/organisations/me", headers=owner["headers"])).json()["data"]
    assert org["seats_used"] == 1


async def test_a_learner_without_an_organisation_gets_a_403(client, learner):
    response = await client.get(f"{API}/organisations/me", headers=learner["headers"])
    assert_error_envelope(response, 403, "forbidden")


async def test_uploading_adds_new_people_and_updates_known_ones_by_email(client, owner, roles):
    first = await upload(
        client,
        owner,
        [
            person("Ngozi Okeke", "Ngozi@Example.com", roles["backend"], "Payments"),
            person("Emeka Obi", "emeka@example.com", roles["frontend"], "Payments"),
        ],
    )
    assert first.status_code == 200, first.text
    assert "X-Sample-Data" not in first.headers
    assert first.json()["data"] == {"added": 2, "updated": 0, "members_total": 2}

    second = await upload(
        client,
        owner,
        [
            person("Ngozi Okeke-Bello", "ngozi@example.com", roles["frontend"], "Lending"),
            person("Halima Sani", "halima@example.com", roles["backend"], "Lending"),
        ],
    )
    assert second.json()["data"] == {"added": 1, "updated": 1, "members_total": 3}

    page = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]
    assert page["total"] == 3 and page["limit"] == 50 and page["offset"] == 0
    by_email = {m["email"]: m for m in page["items"]}
    ngozi = by_email["ngozi@example.com"]
    assert ngozi["full_name"] == "Ngozi Okeke-Bello" and ngozi["department"] == "Lending"
    assert ngozi["role_id"] == roles["frontend"] and ngozi["role_title"] == "Frontend Developer"
    assert ngozi["status"] == "not_invited" and ngozi["latest_level"] is None
    assert isinstance(ngozi["member_id"], int)
    assert [m["full_name"] for m in page["items"]] == sorted(m["full_name"] for m in page["items"])


async def test_the_roster_can_be_filtered_by_department_and_paged(client, owner, roles):
    await upload(
        client,
        owner,
        [
            person("Ada", "ada@example.com", roles["backend"], "Lending"),
            person("Bola", "bola@example.com", roles["backend"], "Payments"),
            person("Chi", "chi@example.com", roles["frontend"], "Lending"),
        ],
    )
    url = f"{API}/organisations/{owner['id']}/members"
    lending = (
        await client.get(url, headers=owner["headers"], params={"department": "lending"})
    ).json()["data"]
    assert [m["full_name"] for m in lending["items"]] == ["Ada", "Chi"] and lending["total"] == 2
    page = (
        await client.get(url, headers=owner["headers"], params={"limit": 1, "offset": 1})
    ).json()["data"]
    assert [m["full_name"] for m in page["items"]] == ["Bola"] and page["total"] == 3
    too_many = await client.get(url, headers=owner["headers"], params={"limit": 101})
    assert_error_envelope(too_many, 422, "validation_error")


async def test_more_people_than_seats_is_a_402_and_nothing_is_saved(client, db, owner, roles):
    db.execute(text("UPDATE organisations SET seats_total = 2 WHERE id = :id"), {"id": owner["id"]})
    db.commit()
    await upload(client, owner, [person("Ada", "ada@example.com", roles["backend"])])
    response = await upload(
        client,
        owner,
        [
            person("Ada Again", "ada@example.com", roles["backend"]),
            person("Bola", "bola@example.com", roles["backend"]),
            person("Chi", "chi@example.com", roles["backend"]),
        ],
    )
    error = assert_error_envelope(response, 402, "payment_required")
    assert "2 seats" in error["message"]
    names = db.execute(
        text("SELECT full_name FROM team_members WHERE organisation_id = :o"), {"o": owner["id"]}
    ).scalars()
    assert list(names) == ["Ada"]
    # updating people already there needs no new seat
    fine = await upload(client, owner, [person("Ada Again", "ada@example.com", roles["backend"])])
    assert fine.json()["data"] == {"added": 0, "updated": 1, "members_total": 1}


async def test_an_unknown_role_is_a_404_and_nothing_is_saved(client, db, owner, roles):
    response = await upload(
        client,
        owner,
        [
            person("Ada", "ada@example.com", roles["backend"]),
            person("Bola", "bola@example.com", 999999),
        ],
    )
    error = assert_error_envelope(response, 404, "not_found")
    assert "999999" in error["message"]
    count = db.execute(text("SELECT count(*) FROM team_members")).scalar_one()
    assert count == 0


async def test_the_same_email_twice_in_one_upload_is_a_400(client, owner, roles):
    response = await upload(
        client,
        owner,
        [
            person("Ada", "ada@example.com", roles["backend"]),
            person("Ada B", "ADA@example.com", roles["frontend"]),
        ],
    )
    error = assert_error_envelope(response, 400, "bad_request")
    assert "ada@example.com" in error["message"]


async def test_an_empty_upload_or_a_bad_email_is_a_422(client, owner, roles):
    assert_error_envelope(await upload(client, owner, []), 422, "validation_error")
    bad = await upload(client, owner, [person("Ada", "not-an-email", roles["backend"])])
    assert_error_envelope(bad, 422, "validation_error")


async def test_each_organisation_sees_only_its_own_roster(client, db, owner, roles):
    rival = _org(db, "Rival Ltd", "rex", role="owner")
    await upload(client, owner, [person("Ada", "ada@example.com", roles["backend"])])
    await upload(client, rival, [person("Ada", "ada@example.com", roles["frontend"])])
    mine = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]
    assert mine["total"] == 1 and mine["items"][0]["role_id"] == roles["backend"]
    theirs = await client.get(
        f"{API}/organisations/{owner['id']}/members", headers=rival["headers"]
    )
    assert_error_envelope(theirs, 404, "not_found")


async def test_recruiters_cannot_see_or_change_the_roster(client, db, owner, roles):
    recruiter = add_member(db, owner, "rita", "recruiter")
    url = f"{API}/organisations/{owner['id']}/members"
    assert_error_envelope(await client.get(url, headers=recruiter), 403, "forbidden")
    response = await client.post(
        url, headers=recruiter, json={"members": [person("Ada", "ada@example.com", roles["backend"])]}
    )
    assert_error_envelope(response, 403, "forbidden")
    me = await client.get(f"{API}/organisations/me", headers=recruiter)
    assert me.status_code == 200 and me.json()["data"]["organisation_id"] == owner["id"]


def add_member(db, org: dict, name: str, role: str) -> dict:
    from tests.integration.test_organisation_users import add_learner, headers_for

    learner_id = add_learner(db, name)
    db.execute(
        text(
            "INSERT INTO organisation_members (organisation_id, learner_id, role) "
            "VALUES (:o, :l, :r)"
        ),
        {"o": org["id"], "l": learner_id, "r": role},
    )
    db.commit()
    return headers_for(db, learner_id)
