"""Day 13: the beginner path, part 1. The intake questionnaire is real (personality, goals,
time and money), and the answers become up to three ranked career paths, each with a match
score, the reasons behind it and the test to start with. The latest intake is kept per person.
Day 14 (part 2): each path carries the programme that best prepares for it. Day 15 (part 3):
the budget answer counts: a path with a programme the person can afford scores higher, and the
programme shown is one within budget when there is one."""

import pytest

from app.core.config import settings
from app.db.seed import load
from tests.integration.conftest import assert_error_envelope

API = settings.API_PREFIX
ROLE_TABLES = ("skills", "subskills", "job_titles", "job_roles", "job_role_skills")


@pytest.fixture
def roles(database):
    with database.begin() as conn:
        load(conn, tables=ROLE_TABLES)


@pytest.fixture
def programmes(database):
    with database.begin() as conn:
        load(conn, tables=(*ROLE_TABLES, "programmes", "programme_roles", "programme_skills"))


async def _questionnaire(client) -> dict:
    response = await client.get(f"{API}/beginner-path/intake")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _answers(questionnaire: dict, **chosen) -> list[dict]:
    answers = []
    for question in questionnaire["questions"]:
        value = chosen.get(question["question_id"], question["options"][0]["value"])
        answers.append(
            {
                "question_id": question["question_id"],
                "values": value if isinstance(value, list) else [value],
            }
        )
    return answers


async def _submit(client, headers, questionnaire, **chosen):
    return await client.post(
        f"{API}/beginner-path/intake",
        headers=headers,
        json={"version": questionnaire["version"], "answers": _answers(questionnaire, **chosen)},
    )


async def test_the_questionnaire_is_public_and_real(client):
    response = await client.get(f"{API}/beginner-path/intake")
    assert response.status_code == 200
    assert "X-Sample-Data" not in response.headers
    data = response.json()["data"]
    assert {q["section"] for q in data["questions"]} == {"personality", "goals", "time", "finances"}
    for question in data["questions"]:
        assert set(question) == {"question_id", "section", "text", "kind", "options"}
        for option in question["options"]:
            assert set(option) == {"value", "label"}


async def test_answers_become_ranked_career_paths(client, learner, roles):
    questionnaire = await _questionnaire(client)
    response = await _submit(
        client,
        learner["headers"],
        questionnaire,
        work_style="data",
        interests=["spreadsheets", "ai"],
        background="maths",
    )
    assert response.status_code == 201, response.text
    assert "X-Sample-Data" not in response.headers
    path = response.json()["data"]
    assert path["intake_id"] >= 1 and path["submitted_at"]
    paths = path["recommendations"]
    assert [p["rank"] for p in paths] == [1, 2, 3]
    assert paths[0]["role_id"] == 103 and paths[0]["title"] == "Data Analyst"
    assert {p["role_id"] for p in paths} <= {101, 102, 103, 104, 105, 106, 107, 108}
    scores = [p["match_score"] for p in paths]
    assert scores == sorted(scores, reverse=True)
    assert paths[0]["reasons"]
    assert paths[0]["programme"] is None  # no programmes loaded in this test


async def test_the_starting_test_is_the_roles_first_testable_skill(client, learner, database):
    with database.begin() as conn:
        load(conn)  # the whole bank: which skills can be tested depends on the questions
    questionnaire = await _questionnaire(client)
    response = await _submit(
        client, learner["headers"], questionnaire, work_style="visual", interests=["build_websites"]
    )
    paths = response.json()["data"]["recommendations"]
    frontend = next(p for p in paths if p["role_id"] == 101)
    assert frontend["starting_test_id"] == 201  # Frontend Web Development


async def test_without_reviewed_questions_there_is_no_starting_test(client, learner, roles):
    questionnaire = await _questionnaire(client)
    response = await _submit(client, learner["headers"], questionnaire, work_style="data")
    for path in response.json()["data"]["recommendations"]:
        assert path["starting_test_id"] is None  # no questions loaded in this test


async def test_my_career_paths_are_my_latest_intake(client, learner, other_learner, roles):
    empty = await client.get(f"{API}/beginner-path/recommendations", headers=learner["headers"])
    assert empty.status_code == 200, empty.text
    assert empty.json()["data"] == {"intake_id": None, "submitted_at": None, "recommendations": []}

    questionnaire = await _questionnaire(client)
    await _submit(client, learner["headers"], questionnaire, work_style="data")
    latest = (
        await _submit(
            client,
            learner["headers"],
            questionnaire,
            work_style="people",
            interests=["talk"],
            background="business",
        )
    ).json()["data"]

    mine = (
        await client.get(f"{API}/beginner-path/recommendations", headers=learner["headers"])
    ).json()["data"]
    assert mine == latest
    assert mine["recommendations"][0]["role_id"] in {106, 107}
    theirs = (
        await client.get(f"{API}/beginner-path/recommendations", headers=other_learner["headers"])
    ).json()["data"]
    assert theirs["recommendations"] == []


async def test_the_answers_are_kept(client, learner, roles, db):
    from sqlalchemy import text

    questionnaire = await _questionnaire(client)
    await _submit(client, learner["headers"], questionnaire, work_style="logic", budget="free_only")
    row = db.execute(text("SELECT learner_id, version, answers FROM beginner_intakes")).one()
    assert row[0] == learner["learner_id"] and row[1] == questionnaire["version"]
    assert row[2]["work_style"] == ["logic"] and row[2]["budget"] == ["free_only"]


@pytest.mark.parametrize(
    "change",
    ["unknown_question", "unknown_value", "two_values_for_one_choice", "missing", "old_version"],
)
async def test_bad_intakes_are_400(client, learner, roles, change):
    questionnaire = await _questionnaire(client)
    answers = _answers(questionnaire)
    version = questionnaire["version"]
    if change == "unknown_question":
        answers.append({"question_id": "nope", "values": ["x"]})
    elif change == "unknown_value":
        answers[0]["values"] = ["not-an-option"]
    elif change == "two_values_for_one_choice":
        answers[0]["values"] = [o["value"] for o in questionnaire["questions"][0]["options"][:2]]
    elif change == "missing":
        answers = answers[1:]
    else:
        version = "2020-01"
    response = await client.post(
        f"{API}/beginner-path/intake",
        headers=learner["headers"],
        json={"version": version, "answers": answers},
    )
    assert_error_envelope(response, 400, "bad_request")


async def test_the_intake_needs_a_login(client, roles):
    questionnaire = await _questionnaire(client)
    response = await client.post(
        f"{API}/beginner-path/intake",
        json={"version": questionnaire["version"], "answers": _answers(questionnaire)},
    )
    assert_error_envelope(response, 401, "unauthenticated")


async def test_each_path_carries_a_programme_for_its_role(client, learner, programmes):
    questionnaire = await _questionnaire(client)
    response = await _submit(
        client, learner["headers"], questionnaire, work_style="logic", interests=["automate"]
    )
    assert response.status_code == 201, response.text
    for path in response.json()["data"]["recommendations"]:
        programme = path["programme"]
        assert programme is not None, path
        detail = (await client.get(f"{API}/programmes/{programme['programme_id']}")).json()
        assert path["role_id"] in detail["data"]["role_ids"]
        assert set(programme) == {
            "programme_id",
            "name",
            "provider",
            "provider_type",
            "mode",
            "duration_weeks",
            "price",
        }


async def test_the_programme_is_kept_with_the_intake(client, learner, programmes):
    questionnaire = await _questionnaire(client)
    given = (await _submit(client, learner["headers"], questionnaire, work_style="visual")).json()[
        "data"
    ]
    mine = (
        await client.get(f"{API}/beginner-path/recommendations", headers=learner["headers"])
    ).json()["data"]
    assert mine == given
    assert all(p["programme"] for p in mine["recommendations"])


def _by_role(response) -> dict[int, dict]:
    assert response.status_code == 201, response.text
    return {p["role_id"]: p for p in response.json()["data"]["recommendations"]}


DATA_PERSON = {"work_style": "data", "interests": ["spreadsheets", "ai"], "background": "maths"}


async def test_free_only_shows_free_programmes_where_there_are_any(client, learner, programmes):
    questionnaire = await _questionnaire(client)
    paths = _by_role(
        await _submit(
            client,
            learner["headers"],
            questionnaire,
            work_style="visual",
            interests=["build_websites", "content"],
            budget="free_only",
        )
    )
    frontend = paths[101]
    assert frontend["programme"]["price"]["amount"] == 0
    assert frontend["programme_within_budget"] is True
    assert "There is a free programme for this path" in frontend["reasons"]


async def test_a_path_with_nothing_affordable_shows_the_cheapest_and_says_so(
    client, learner, programmes
):
    questionnaire = await _questionnaire(client)
    paths = _by_role(
        await _submit(client, learner["headers"], questionnaire, **DATA_PERSON, budget="free_only")
    )
    analyst = paths[103]
    assert analyst["programme_within_budget"] is False
    assert analyst["programme"]["programme_id"] == 303  # the cheapest Data Analyst programme
    assert not any("budget" in reason or "free" in reason for reason in analyst["reasons"])


async def test_an_affordable_programme_raises_the_match(client, learner, programmes):
    questionnaire = await _questionnaire(client)
    tight = _by_role(
        await _submit(client, learner["headers"], questionnaire, **DATA_PERSON, budget="free_only")
    )
    open_budget = _by_role(
        await _submit(client, learner["headers"], questionnaire, **DATA_PERSON, budget="over_200k")
    )
    assert open_budget[103]["match_score"] > tight[103]["match_score"]
    assert open_budget[103]["programme_within_budget"] is True
    assert open_budget[103]["programme"]["programme_id"] == 305  # Incubate's own first
    assert "There is a programme within your budget" in open_budget[103]["reasons"]


async def test_under_50k_never_shows_a_programme_over_it_when_one_fits(client, learner, programmes):
    questionnaire = await _questionnaire(client)
    paths = _by_role(
        await _submit(
            client,
            learner["headers"],
            questionnaire,
            work_style="logic",
            interests=["automate"],
            budget="under_50k",
        )
    )
    for path in paths.values():
        if path["programme_within_budget"]:
            assert path["programme"]["price"]["amount"] < 5_000_000, path
    assert paths[102]["programme"]["programme_id"] == 303  # NGN 45,000, not the 200k one


async def test_without_programmes_the_budget_changes_nothing(client, learner, roles):
    questionnaire = await _questionnaire(client)
    free = _by_role(
        await _submit(client, learner["headers"], questionnaire, **DATA_PERSON, budget="free_only")
    )
    rich = _by_role(
        await _submit(client, learner["headers"], questionnaire, **DATA_PERSON, budget="over_200k")
    )
    assert {r: p["match_score"] for r, p in free.items()} == {
        r: p["match_score"] for r, p in rich.items()
    }
    assert all(p["programme"] is None for p in free.values())
    assert all(p["programme_within_budget"] is None for p in free.values())
