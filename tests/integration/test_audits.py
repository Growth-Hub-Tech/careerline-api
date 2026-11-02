"""Day 22: organisation audit part 2: audits that test the team for their roles, and benchmarks.

POST /organisations/{id}/audits picks the roster people in the audit's roles (or the member_ids
given) and, unless it is a draft, invites each of them to every testable skill of their role
(team invitations, free for them, any account can accept). The audit is in_progress until every
invitation is finished, then completed. Benchmarks compare each role and skill with its target
level (what the role needs) and with everyone's average on CareerLine (the industry average,
shown once at least 5 people have results in that skill).
"""

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import _make_learner, assert_error_envelope, take_test
from tests.integration.test_recruiter import _org
from tests.integration.test_team_roster import add_role, person, upload

API = settings.API_PREFIX


@pytest.fixture
def owner(db) -> dict:
    return _org(db, "Acme Fintech", "olu", role="owner")


@pytest.fixture
def untestable(db) -> int:
    return db.execute(
        text(
            "INSERT INTO skills (skill_name, category, skill_descr) "
            "VALUES ('Cobol', 'Programming', 'No questions yet') RETURNING skill_id"
        )
    ).scalar_one()


@pytest.fixture
def roles(db, skill, untestable) -> dict:
    db.commit()
    return {
        "backend": add_role(
            db,
            "backend-dev",
            "Backend Developer",
            [(skill["skill_id"], "MID"), (untestable, "MID")],
        ),
        "frontend": add_role(
            db, "frontend-dev", "Frontend Developer", [(skill["skill_id"], "JUNIOR")]
        ),
        "nothing": add_role(db, "cobol-dev", "Cobol Developer", [(untestable, "MID")]),
    }


@pytest.fixture
async def roster(client, owner, roles) -> dict:
    response = await upload(
        client,
        owner,
        [
            person("Ada Obi", "ada@example.com", roles["backend"], "Payments"),
            person("Bola Ade", "bola@example.com", roles["backend"], "Lending"),
            person("Chi Eze", "chi@example.com", roles["frontend"], "Lending"),
            person("Dayo Cole", "dayo@example.com", roles["nothing"], "Lending"),
        ],
    )
    assert response.status_code == 200, response.text
    members = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]["items"]
    return {m["email"]: m for m in members}


async def start(client, owner, **body):
    payload = {"name": "Q4 engineering audit", **body}
    return await client.post(
        f"{API}/organisations/{owner['id']}/audits", headers=owner["headers"], json=payload
    )


def team_invitations(db, email: str) -> list:
    return db.execute(
        text(
            "SELECT token, skill_id, status, kind, audit_id FROM invitations "
            "WHERE email = :e ORDER BY id"
        ),
        {"e": email},
    ).all()


async def finish(client, db, skill, email: str, who: dict, right=lambda info: True) -> None:
    (row,) = [r for r in team_invitations(db, email) if r.status == "sent"]
    accepted = await client.post(
        f"{API}/invitations/token/{row.token}/accept", headers=who["headers"]
    )
    assert accepted.status_code == 200, accepted.text
    done = await take_test(client, who["headers"], skill, right)
    assert done["status"] == "completed"


async def test_an_audit_invites_everyone_in_its_roles_to_each_testable_skill(
    client, db, owner, roles, roster, skill
):
    response = await start(client, owner, role_ids=[roles["backend"], roles["frontend"]])
    assert response.status_code == 201, response.text
    assert "X-Sample-Data" not in response.headers
    audit = response.json()["data"]
    assert (
        audit["status"] == "in_progress" and audit["started_at"] and audit["completed_at"] is None
    )
    assert audit["members_total"] == 3 and audit["members_completed"] == 0
    assert audit["role_ids"] == [roles["backend"], roles["frontend"]]
    assert audit["benchmarks"] == []
    # one invitation per person for the role's testable skill (Cobol has no questions)
    for email in ("ada@example.com", "bola@example.com", "chi@example.com"):
        rows = team_invitations(db, email)
        assert [(r.skill_id, r.status, r.kind, r.audit_id) for r in rows] == [
            (skill["skill_id"], "sent", "team_member", audit["audit_id"])
        ]
    assert team_invitations(db, "dayo@example.com") == []
    emails = db.execute(
        text("SELECT to_address FROM email_outbox WHERE template = 'invitation' ORDER BY id")
    ).scalars()
    assert sorted(emails) == ["ada@example.com", "bola@example.com", "chi@example.com"]
    members = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]["items"]
    assert {m["email"]: m["status"] for m in members} == {
        "ada@example.com": "invited",
        "bola@example.com": "invited",
        "chi@example.com": "invited",
        "dayo@example.com": "not_invited",
    }


async def test_member_ids_pick_people_and_must_be_on_the_roster_in_those_roles(
    client, owner, roles, roster
):
    ada = roster["ada@example.com"]["member_id"]
    chi = roster["chi@example.com"]["member_id"]
    one = await start(client, owner, role_ids=[roles["backend"]], member_ids=[ada])
    assert one.json()["data"]["members_total"] == 1
    wrong_role = await start(client, owner, role_ids=[roles["backend"]], member_ids=[chi])
    error = assert_error_envelope(wrong_role, 400, "bad_request")
    assert "Chi Eze" in error["message"]
    assert_error_envelope(
        await start(client, owner, role_ids=[roles["backend"]], member_ids=[999999]),
        404,
        "not_found",
    )
    assert_error_envelope(await start(client, owner, role_ids=[999999]), 404, "not_found")


async def test_an_audit_needs_people_and_a_testable_skill(client, owner, roles, roster, db):
    nobody = add_role(db, "qa", "QA Engineer")
    error = assert_error_envelope(await start(client, owner, role_ids=[nobody]), 400, "bad_request")
    assert "roster" in error["message"]
    error = assert_error_envelope(
        await start(client, owner, role_ids=[roles["nothing"]]), 400, "bad_request"
    )
    assert "no test" in error["message"]
    assert_error_envelope(await start(client, owner, role_ids=[]), 422, "validation_error")


async def test_a_draft_sends_nothing_until_it_is_started(client, db, owner, roles, roster):
    draft = (
        await start(client, owner, role_ids=[roles["frontend"]], send_invitations=False)
    ).json()["data"]
    assert draft["status"] == "draft" and draft["started_at"] is None
    assert draft["members_total"] == 1
    assert team_invitations(db, "chi@example.com") == []
    url = f"{API}/organisations/{owner['id']}/audits/{draft['audit_id']}/start"
    started = await client.post(url, headers=owner["headers"])
    assert started.status_code == 200, started.text
    assert started.json()["data"]["status"] == "in_progress"
    assert len(team_invitations(db, "chi@example.com")) == 1
    again = await client.post(url, headers=owner["headers"])
    assert_error_envelope(again, 409, "conflict")


async def test_finished_tests_complete_members_and_then_the_audit_with_benchmarks(
    client, db, owner, roles, roster, skill
):
    audit = (await start(client, owner, role_ids=[roles["backend"], roles["frontend"]])).json()[
        "data"
    ]
    url = f"{API}/organisations/{owner['id']}/audits/{audit['audit_id']}"
    ada = await _make_learner(client, "ada.personal@example.com", "Ada Obi")
    await finish(client, db, skill, "ada@example.com", ada)  # all right: ADVANCED

    now = (await client.get(url, headers=owner["headers"])).json()["data"]
    assert now["status"] == "in_progress" and now["members_completed"] == 1
    (bench,) = [b for b in now["benchmarks"] if b["role_id"] == roles["backend"]]
    assert bench["skill_id"] == skill["skill_id"] and bench["skill_name"] == "Python"
    assert bench["role_title"] == "Backend Developer" and bench["target_level"] == "MID"
    assert bench["members_tested"] == 1 and bench["members_at_or_above_target"] == 1
    score = db.execute(text("SELECT score FROM skill_history")).scalar_one()
    assert bench["team_average_score"] == float(score)
    assert bench["industry_average_score"] is None  # fewer than 5 results in Python

    members = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]["items"]
    by_email = {m["email"]: m for m in members}
    assert by_email["ada@example.com"]["status"] == "completed"
    assert by_email["ada@example.com"]["latest_level"] == "ADVANCED"

    for email, name in (("bola@example.com", "Bola Ade"), ("chi@example.com", "Chi Eze")):
        who = await _make_learner(client, f"x.{email}", name)
        await finish(client, db, skill, email, who, right=lambda info: False)
    done = (await client.get(url, headers=owner["headers"])).json()["data"]
    assert done["status"] == "completed" and done["completed_at"]
    assert done["members_completed"] == 3
    (backend,) = [b for b in done["benchmarks"] if b["role_id"] == roles["backend"]]
    assert backend["members_tested"] == 2 and backend["members_at_or_above_target"] == 1
    scores = db.execute(text("SELECT score FROM skill_history ORDER BY id")).scalars().all()
    assert backend["team_average_score"] == round((scores[0] + scores[1]) / 2, 1)
    (frontend,) = [b for b in done["benchmarks"] if b["role_id"] == roles["frontend"]]
    assert frontend["target_level"] == "JUNIOR" and frontend["members_tested"] == 1


async def test_the_industry_average_shows_once_five_people_have_results(
    client, db, owner, roles, roster, skill
):
    for n in range(4):
        someone = await _make_learner(client, f"self{n}@example.com", f"Self Tester {n}")
        await take_test(client, someone["headers"], skill, right=lambda info: False)
    audit = (await start(client, owner, role_ids=[roles["frontend"]])).json()["data"]
    chi = await _make_learner(client, "chi.personal@example.com", "Chi Eze")
    await finish(client, db, skill, "chi@example.com", chi)
    got = (
        await client.get(
            f"{API}/organisations/{owner['id']}/audits/{audit['audit_id']}",
            headers=owner["headers"],
        )
    ).json()["data"]
    (bench,) = got["benchmarks"]
    scores = db.execute(text("SELECT score FROM skill_history")).scalars().all()
    assert len(scores) == 5
    assert bench["industry_average_score"] == round(sum(scores) / 5, 1)


async def test_audits_are_listed_newest_first_and_stay_in_their_organisation(
    client, db, owner, roles, roster
):
    first = (await start(client, owner, name="First", role_ids=[roles["frontend"]])).json()["data"]
    await start(client, owner, name="Second", role_ids=[roles["backend"]], send_invitations=False)
    url = f"{API}/organisations/{owner['id']}/audits"
    page = (await client.get(url, headers=owner["headers"])).json()["data"]
    assert [a["name"] for a in page["items"]] == ["Second", "First"]
    assert page["total"] == 2 and page["limit"] == 20
    assert "benchmarks" not in page["items"][0]
    assert_error_envelope(
        await client.get(url, headers=owner["headers"], params={"limit": 0}),
        422,
        "validation_error",
    )
    rival = _org(db, "Rival Ltd", "rex", role="owner")
    rival_url = f"{API}/organisations/{rival['id']}/audits/{first['audit_id']}"
    assert_error_envelope(await client.get(rival_url, headers=rival["headers"]), 404, "not_found")
    missing = f"{url}/999999"
    assert_error_envelope(await client.get(missing, headers=owner["headers"]), 404, "not_found")
