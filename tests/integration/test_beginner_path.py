"""Day 13: the beginner path, part 1. The intake questionnaire is real (personality, goals,
time and money), and the answers become up to three ranked career paths, each with a match
score, the reasons behind it and the test to start with. The latest intake is kept per person.
Programmes for each path come later (Day 14)."""

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
    assert paths[0]["reasons"] and paths[0]["programme"] is None


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
