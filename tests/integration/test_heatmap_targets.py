"""Day 23: organisation audit part 3: targets and the capability heatmap.

PUT /organisations/{id}/targets replaces the organisation's targets: the level each role should
reach in each skill, with an optional due date. GET shows each one with how many people in that
role meet it (their newest team result in that skill). Audit benchmarks use the organisation's
target when there is one, else what the role needs.

GET /organisations/{id}/heatmap: rows are departments, roles or people; columns are the skills
of their roles; each cell is the average of the people's newest team results in that skill, its
level, and a band against the target (strong: meets it, developing: one level short, weak:
further, not_tested). With audit_id: only that audit's people and results.
"""

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import _make_learner, assert_error_envelope
from tests.integration.test_audits import finish, start, untestable  # noqa: F401
from tests.integration.test_recruiter import _org
from tests.integration.test_team_roster import add_role, person, upload

API = settings.API_PREFIX


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
            person("Dayo Cole", "dayo@example.com", roles["frontend"], None),
        ],
    )
    members = (
        await client.get(f"{API}/organisations/{owner['id']}/members", headers=owner["headers"])
    ).json()["data"]["items"]
    return {m["email"]: m for m in members}


async def put_targets(client, owner, items):
    return await client.put(
        f"{API}/organisations/{owner['id']}/targets",
        headers=owner["headers"],
        json={"items": items},
    )


async def get_targets(client, owner):
    response = await client.get(
        f"{API}/organisations/{owner['id']}/targets", headers=owner["headers"]
    )
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    return response.json()["data"]


async def heatmap(client, owner, **params):
    response = await client.get(
        f"{API}/organisations/{owner['id']}/heatmap", headers=owner["headers"], params=params
    )
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    return response.json()["data"]


async def test_targets_start_empty_and_are_replaced_as_a_whole(client, owner, roles, roster, skill):
    assert await get_targets(client, owner) == {"organisation_id": owner["id"], "items": []}
    response = await put_targets(
        client,
        owner,
        [
            {
                "role_id": roles["backend"],
                "skill_id": skill["skill_id"],
                "target_level": "ADVANCED",
                "due_date": "2027-03-31",
            },
            {"role_id": roles["frontend"], "skill_id": skill["skill_id"], "target_level": "MID"},
        ],
    )
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert [
        (t["role_title"], t["skill_name"], t["target_level"], t["due_date"]) for t in items
    ] == [
        ("Backend Developer", "Python", "ADVANCED", "2027-03-31"),
        ("Frontend Developer", "Python", "MID", None),
    ]
    assert [(t["members_total"], t["members_meeting"], t["progress_percent"]) for t in items] == [
        (2, 0, 0),
        (2, 0, 0),
    ]
    assert (await get_targets(client, owner))["items"] == items
    replaced = await put_targets(
        client,
        owner,
        [{"role_id": roles["frontend"], "skill_id": skill["skill_id"], "target_level": "JUNIOR"}],
    )
    assert [t["role_id"] for t in replaced.json()["data"]["items"]] == [roles["frontend"]]
    cleared = await put_targets(client, owner, [])
    assert cleared.json()["data"]["items"] == []


async def test_bad_targets_are_refused_and_nothing_changes(client, owner, roles, skill):
    good = {"role_id": roles["backend"], "skill_id": skill["skill_id"], "target_level": "MID"}
    await put_targets(client, owner, [good])
    assert_error_envelope(
        await put_targets(client, owner, [good, {**good, "target_level": "ADVANCED"}]),
        400,
        "bad_request",
    )
    assert_error_envelope(
        await put_targets(client, owner, [{**good, "role_id": 999999}]), 404, "not_found"
    )
    assert_error_envelope(
        await put_targets(client, owner, [{**good, "skill_id": 999999}]), 404, "not_found"
    )
    assert_error_envelope(
        await put_targets(client, owner, [{**good, "target_level": "GURU"}]),
        422,
        "validation_error",
    )
    assert [t["target_level"] for t in (await get_targets(client, owner))["items"]] == ["MID"]


async def test_progress_counts_people_whose_newest_result_meets_the_target(
    client, db, owner, roles, roster, skill
):
    await start(client, owner, role_ids=[roles["backend"]])
    ada = await _make_learner(client, "ada.p@example.com", "Ada Obi")
    await finish(client, db, skill, "ada@example.com", ada)  # ADVANCED
    await put_targets(
        client,
        owner,
        [{"role_id": roles["backend"], "skill_id": skill["skill_id"], "target_level": "MID"}],
    )
    (target,) = (await get_targets(client, owner))["items"]
    assert (target["members_total"], target["members_meeting"], target["progress_percent"]) == (
        2,
        1,
        50,
    )


async def test_audit_benchmarks_use_the_organisations_target(
    client, db, owner, roles, roster, skill
):
    audit = (await start(client, owner, role_ids=[roles["frontend"]])).json()["data"]
    chi = await _make_learner(client, "chi.p@example.com", "Chi Eze")
    await finish(
        client, db, skill, "chi@example.com", chi, right=lambda info: info["level"] == "BEGINNER"
    )
    url = f"{API}/organisations/{owner['id']}/audits/{audit['audit_id']}"
    before = (await client.get(url, headers=owner["headers"])).json()["data"]["benchmarks"][0]
    assert before["target_level"] == "JUNIOR"
    await put_targets(
        client,
        owner,
        [{"role_id": roles["frontend"], "skill_id": skill["skill_id"], "target_level": "ADVANCED"}],
    )
    after = (await client.get(url, headers=owner["headers"])).json()["data"]["benchmarks"][0]
    assert after["target_level"] == "ADVANCED" and after["members_at_or_above_target"] == 0


async def test_an_empty_roster_has_an_empty_heatmap(client, owner, roles, skill):
    data = await heatmap(client, owner)
    assert data == {
        "organisation_id": owner["id"],
        "audit_id": None,
        "group_by": "department",
        "skills": [],
        "rows": [],
    }


async def test_the_heatmap_by_department_role_and_person(
    client,
    db,
    owner,
    roles,
    roster,
    skill,
    untestable,  # noqa: F811
):
    await start(client, owner, role_ids=[roles["backend"], roles["frontend"]])
    ada = await _make_learner(client, "ada.p@example.com", "Ada Obi")
    await finish(client, db, skill, "ada@example.com", ada)  # all right
    bola = await _make_learner(client, "bola.p@example.com", "Bola Ade")
    await finish(client, db, skill, "bola@example.com", bola, right=lambda info: False)
    scores = dict(
        db.execute(
            text(
                "SELECT i.email, h.score FROM skill_history h JOIN invitations i "
                "ON i.attempt_id = h.attempt_id"
            )
        ).all()
    )

    by_department = await heatmap(client, owner)
    assert by_department["group_by"] == "department" and by_department["audit_id"] is None
    assert [s["skill_name"] for s in by_department["skills"]] == ["Python", "Cobol"]
    rows = {r["label"]: r for r in by_department["rows"]}
    assert list(rows) == ["Lending", "No department", "Payments"]
    assert rows["Lending"]["key"] == "lending" and rows["Lending"]["members"] == 2
    assert rows["No department"]["key"] == "none"
    payments_python = rows["Payments"]["cells"][0]
    assert payments_python["skill_id"] == skill["skill_id"]
    assert payments_python["average_score"] == float(scores["ada@example.com"])
    assert payments_python["members_tested"] == 1 and payments_python["band"] == "strong"
    assert payments_python["level"] == "ADVANCED"
    lending_python = rows["Lending"]["cells"][0]
    assert lending_python["members_tested"] == 1  # Chi has not finished yet
    assert lending_python["level"] == "BEGINNER" and lending_python["band"] == "weak"  # MID needed
    cobol = rows["Lending"]["cells"][1]
    assert cobol == {
        "skill_id": untestable,
        "average_score": None,
        "level": None,
        "members_tested": 0,
        "band": "not_tested",
    }
    assert rows["No department"]["cells"][0]["band"] == "not_tested"

    by_role = await heatmap(client, owner, group_by="role")
    role_rows = {r["label"]: r for r in by_role["rows"]}
    assert list(role_rows) == ["Backend Developer", "Frontend Developer"]
    assert role_rows["Backend Developer"]["key"] == str(roles["backend"])
    expected = round((scores["ada@example.com"] + scores["bola@example.com"]) / 2, 1)
    assert role_rows["Backend Developer"]["cells"][0]["average_score"] == expected
    assert role_rows["Backend Developer"]["cells"][0]["members_tested"] == 2

    by_person = await heatmap(client, owner, group_by="member")
    labels = [r["label"] for r in by_person["rows"]]
    assert labels == ["Ada Obi", "Bola Ade", "Chi Eze", "Dayo Cole"]
    assert by_person["rows"][0]["key"] == str(roster["ada@example.com"]["member_id"])
    for row in by_person["rows"]:
        assert [c["skill_id"] for c in row["cells"]] == [s["skill_id"] for s in by_person["skills"]]


async def test_the_heatmap_of_one_audit(client, db, owner, roles, roster, skill):
    first = (await start(client, owner, role_ids=[roles["frontend"]])).json()["data"]
    chi = await _make_learner(client, "chi.p@example.com", "Chi Eze")
    await finish(client, db, skill, "chi@example.com", chi)
    second = (await start(client, owner, role_ids=[roles["backend"]])).json()["data"]
    one = await heatmap(client, owner, group_by="member", audit_id=first["audit_id"])
    assert one["audit_id"] == first["audit_id"]
    assert [r["label"] for r in one["rows"]] == ["Chi Eze", "Dayo Cole"]
    assert one["rows"][0]["cells"][0]["members_tested"] == 1
    other = await heatmap(client, owner, group_by="member", audit_id=second["audit_id"])
    assert [r["label"] for r in other["rows"]] == ["Ada Obi", "Bola Ade"]
    assert all(c["band"] == "not_tested" for r in other["rows"] for c in r["cells"])
    missing = await client.get(
        f"{API}/organisations/{owner['id']}/heatmap",
        headers=owner["headers"],
        params={"audit_id": 999999},
    )
    assert_error_envelope(missing, 404, "not_found")
    bad = await client.get(
        f"{API}/organisations/{owner['id']}/heatmap",
        headers=owner["headers"],
        params={"group_by": "shoe_size"},
    )
    assert_error_envelope(bad, 422, "validation_error")
