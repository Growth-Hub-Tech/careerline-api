"""Day 24: pre/post re-test (PRD 4.2): take a test again after training and see the change.

- A person's result shows their previous result in the same skill and the score change.
- An organisation re-tests an audit: POST /organisations/{id}/audits/{audit_id}/retest makes a new
  audit for the same people (or some of them) and the same tests, linked to the first one
  (baseline_audit_id). Its benchmarks show the baseline average and the change, and
  GET .../audits/{audit_id}/deltas shows each person's before, after and change per skill.
"""

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import _make_learner, assert_error_envelope, take_test
from tests.integration.test_audits import finish, start, untestable  # noqa: F401
from tests.integration.test_recruiter import _org
from tests.integration.test_team_roster import add_role, person, upload

API = settings.API_PREFIX


@pytest.fixture(autouse=True)
def no_retest_cooldown(monkeypatch):
    # Day 31: the cooldown has its own tests (test_day31.py); these check the re-test itself
    monkeypatch.setattr(settings, "RETEST_COOLDOWN_DAYS", 0)


def only_beginner(info) -> bool:
    return info["level"] == "BEGINNER"


async def test_a_result_shows_the_previous_result_in_that_skill_and_the_change(
    client, learner, skill
):
    first = await take_test(client, learner["headers"], skill, right=only_beginner)
    first_id = first["attempt_id"]
    one = (await client.get(f"{API}/results/{first_id}", headers=learner["headers"])).json()["data"]
    assert one["previous_result"] is None and one["score_delta"] is None

    second = await take_test(client, learner["headers"], skill)
    two = (
        await client.get(f"{API}/results/{second['attempt_id']}", headers=learner["headers"])
    ).json()["data"]
    previous = two["previous_result"]
    assert previous["result_id"] == first_id
    assert previous["level"] == one["level"]
    assert previous["percentage_score"] == one["percentage_score"]
    assert previous["completed_at"] == one["completed_at"]
    assert two["score_delta"] == two["percentage_score"] - one["percentage_score"]
    assert two["score_delta"] > 0
    # the first result still compares with nothing earlier
    again = (await client.get(f"{API}/results/{first_id}", headers=learner["headers"])).json()
    assert again["data"]["previous_result"] is None


@pytest.fixture
def owner(db) -> dict:
    return _org(db, "Acme Fintech", "olu", role="owner")


@pytest.fixture
def roles(db, skill, untestable) -> dict:  # noqa: F811
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
    }


@pytest.fixture
async def roster(client, owner, roles) -> dict:
    await upload(
        client,
        owner,
        [
            person("Ada Obi", "ada@example.com", roles["backend"], "Payments"),
            person("Bola Ade", "bola@example.com", roles["backend"], "Lending"),
            person("Chi Eze", "chi@example.com", roles["frontend"], "Lending"),
        ],
    )
    members = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]["items"]
    return {m["email"]: m for m in members}


async def retest(client, owner, audit_id: int, **body):
    return await client.post(
        f"{API}/organisations/{owner['id']}/audits/{audit_id}/retest",
        headers=owner["headers"],
        json=body,
    )


async def test_a_retest_invites_the_same_people_to_the_same_tests_again(
    client, db, owner, roles, roster, skill
):
    first = (await start(client, owner, role_ids=[roles["backend"]])).json()["data"]
    assert first["baseline_audit_id"] is None
    response = await retest(client, owner, first["audit_id"])
    assert response.status_code == 201, response.text
    second = response.json()["data"]
    assert second["baseline_audit_id"] == first["audit_id"]
    assert second["name"] == "Q4 engineering audit (re-test)"
    assert second["role_ids"] == first["role_ids"] and second["members_total"] == 2
    assert second["status"] == "in_progress"
    rows = db.execute(
        text("SELECT audit_id, email, skill_id FROM invitations ORDER BY audit_id, email")
    ).all()
    assert [(r.audit_id, r.email) for r in rows] == [
        (first["audit_id"], "ada@example.com"),
        (first["audit_id"], "bola@example.com"),
        (second["audit_id"], "ada@example.com"),
        (second["audit_id"], "bola@example.com"),
    ]
    listed = (
        await client.get(f"{API}/organisations/{owner['id']}/audits", headers=owner["headers"])
    ).json()["data"]["items"]
    assert [a["baseline_audit_id"] for a in listed] == [first["audit_id"], None]


async def test_a_retest_can_pick_some_people_be_a_draft_and_be_named(
    client, db, owner, roles, roster
):
    first = (await start(client, owner, role_ids=[roles["backend"], roles["frontend"]])).json()[
        "data"
    ]
    ada = roster["ada@example.com"]["member_id"]
    draft = (
        await retest(
            client,
            owner,
            first["audit_id"],
            name="After training",
            member_ids=[ada],
            send_invitations=False,
        )
    ).json()["data"]
    assert draft["name"] == "After training" and draft["status"] == "draft"
    assert draft["members_total"] == 1
    started = await client.post(
        f"{API}/organisations/{owner['id']}/audits/{draft['audit_id']}/start",
        headers=owner["headers"],
    )
    assert started.json()["data"]["status"] == "in_progress"
    emails = db.execute(
        text("SELECT email FROM invitations WHERE audit_id = :a"), {"a": draft["audit_id"]}
    ).scalars()
    assert list(emails) == ["ada@example.com"]


async def test_retest_errors(client, db, owner, roles, roster):
    draft = (
        await start(client, owner, role_ids=[roles["backend"]], send_invitations=False)
    ).json()["data"]
    assert_error_envelope(await retest(client, owner, draft["audit_id"]), 409, "conflict")
    first = (await start(client, owner, role_ids=[roles["backend"]])).json()["data"]
    chi = roster["chi@example.com"]["member_id"]
    error = assert_error_envelope(
        await retest(client, owner, first["audit_id"], member_ids=[chi]), 400, "bad_request"
    )
    assert "Chi Eze" in error["message"]
    assert_error_envelope(await retest(client, owner, 999999), 404, "not_found")
    deltas = await client.get(
        f"{API}/organisations/{owner['id']}/audits/{first['audit_id']}/deltas",
        headers=owner["headers"],
    )
    assert_error_envelope(deltas, 400, "bad_request")


async def test_deltas_and_benchmarks_show_the_change_after_training(
    client, db, owner, roles, roster, skill
):
    first = (await start(client, owner, role_ids=[roles["backend"]])).json()["data"]
    ada = await _make_learner(client, "ada.p@example.com", "Ada Obi")
    await finish(client, db, skill, "ada@example.com", ada, right=only_beginner)
    bola = await _make_learner(client, "bola.p@example.com", "Bola Ade")
    await finish(client, db, skill, "bola@example.com", bola, right=only_beginner)

    second = (await retest(client, owner, first["audit_id"])).json()["data"]
    url = f"{API}/organisations/{owner['id']}/audits/{second['audit_id']}"
    pending = (await client.get(f"{url}/deltas", headers=owner["headers"])).json()["data"]
    assert pending["audit_id"] == second["audit_id"]
    assert pending["baseline_audit_id"] == first["audit_id"]
    assert [i["full_name"] for i in pending["items"]] == ["Ada Obi", "Bola Ade"]
    for item in pending["items"]:
        assert item["skill_id"] == skill["skill_id"] and item["skill_name"] == "Python"
        assert item["before_score"] is not None and item["before_level"] is not None
        assert item["after_score"] is None and item["after_level"] is None
        assert item["score_delta"] is None

    await finish(client, db, skill, "ada@example.com", ada)  # after training: all right
    done = (await client.get(f"{url}/deltas", headers=owner["headers"])).json()["data"]
    ada_row = done["items"][0]
    assert ada_row["after_score"] > ada_row["before_score"]
    assert ada_row["score_delta"] == ada_row["after_score"] - ada_row["before_score"]
    assert ada_row["after_level"] == "ADVANCED"

    (bench,) = (await client.get(url, headers=owner["headers"])).json()["data"]["benchmarks"]
    baseline = (
        await client.get(
            f"{API}/organisations/{owner['id']}/audits/{first['audit_id']}",
            headers=owner["headers"],
        )
    ).json()["data"]["benchmarks"][0]
    assert bench["baseline_average_score"] == baseline["team_average_score"]
    assert bench["score_delta"] == round(
        bench["team_average_score"] - baseline["team_average_score"], 1
    )
    assert baseline["baseline_average_score"] is None and baseline["score_delta"] is None
