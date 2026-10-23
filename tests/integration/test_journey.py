from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import answers_for, start_attempt, submit

API = settings.API_PREFIX


async def test_full_learner_journey(client, learner, skill):
    headers = learner["headers"]
    lists_id, functions_id = skill["subskill_ids"]

    # 1. Skills and subskills
    skills = (await client.get(f"{API}/skills/")).json()["data"]
    assert skills["total"] == 1
    assert skills["skills"][0]["skill_name"] == "Python"
    subskills = (await client.get(f"{API}/skills/{skill['skill_id']}/subskills")).json()["data"]
    assert subskills["total_subskills"] == 2

    # 2. Start an attempt: the questions come back without the answers
    attempt = await start_attempt(client, headers, skill["skill_id"])
    assert attempt["declared_level"] == "JUNIOR"
    assert attempt["total_questions"] == 6
    for question in attempt["questions"]:
        assert len(question["options"]) == 3
        for option in question["options"]:
            assert set(option) == {"option_id", "option_text"}

    # 3. Submit: every Lists answer right, every Functions answer wrong -> 3/6 = 50%
    response = await submit(
        client, headers, attempt["attempt_id"], answers_for(attempt, skill, {lists_id})
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    assert result["score"] == 3
    assert result["total_possible"] == 6
    assert result["percentage"] == 50.0
    assert result["status"] == "failed"
    assert result["confirmed_level"] is None
    assert result["level_suggestion"] == "BEGINNER"
    assert result["subskill_breakdown"][str(lists_id)] == {"correct": 3, "total": 3}
    assert result["subskill_breakdown"][str(functions_id)] == {"correct": 0, "total": 3}

    # 4. Recommendations: only the weak subskill, from the fallback text (no OpenAI key in tests)
    recommendations = response.json()["data"]["recommendations"]
    assert recommendations["total_weak_areas"] == 1
    weak = recommendations["recommendations"][0]
    assert weak["subskill_id"] == functions_id
    assert weak["recommendation"].startswith("Dedicate focused time to Functions")

    # 5. The result can be read back
    detail = (await client.get(f"{API}/attempts/{attempt['attempt_id']}", headers=headers)).json()
    assert detail["data"]["attempt"]["attempt_status"] == "failed"
    assert detail["data"]["attempt"]["overall_percentage"] == 50.0

    history = await client.get(f"{API}/attempts/learner/{learner['learner_id']}", headers=headers)
    assert [a["attempt_id"] for a in history.json()["data"]["attempts"]] == [attempt["attempt_id"]]

    pathway = await client.get(
        f"{API}/recommendations/pathway/{learner['learner_id']}/{skill['skill_id']}",
        headers=headers,
    )
    assert pathway.status_code == 200
    steps = pathway.json()["data"]["learning_pathway"]
    assert [step["subskill_name"] for step in steps] == ["Functions"]


async def test_passing_confirms_the_declared_level_for_that_skill(client, learner, skill, db):
    headers = learner["headers"]
    attempt = await start_attempt(client, headers, skill["skill_id"])

    response = await submit(client, headers, attempt["attempt_id"], answers_for(attempt, skill))

    result = response.json()["data"]["result"]
    assert result["percentage"] == 100.0
    assert result["status"] == "passed"
    assert result["confirmed_level"] == "JUNIOR"
    assert response.json()["data"]["recommendations"]["recommendations"] == []

    levels = await client.get(
        f"{API}/recommendations/levels/{learner['learner_id']}", headers=headers
    )
    assert levels.json()["data"]["confirmed_levels"] == [
        {"skill_id": skill["skill_id"], "skill_name": "Python", "level": "JUNIOR"}
    ]
    # The level row is saved together with its skill
    row = db.execute(
        text("SELECT skill_id, attempt_id FROM learner_level WHERE learner_id = :id"),
        {"id": learner["learner_id"]},
    ).one()
    assert tuple(row) == (skill["skill_id"], attempt["attempt_id"])


async def test_second_submit_of_the_same_attempt_is_409(client, learner, skill):
    headers = learner["headers"]
    attempt = await start_attempt(client, headers, skill["skill_id"])
    answers = answers_for(attempt, skill)
    first = await submit(client, headers, attempt["attempt_id"], answers)
    assert first.status_code == 200

    second = await submit(client, headers, attempt["attempt_id"], answers)

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


async def test_unanswered_questions_count_as_wrong(client, learner, skill):
    headers = learner["headers"]
    attempt = await start_attempt(client, headers, skill["skill_id"])
    one_right = answers_for(attempt, skill)[:1]

    response = await submit(client, headers, attempt["attempt_id"], one_right)

    result = response.json()["data"]["result"]
    assert (result["score"], result["total_possible"]) == (1, 6)
    assert result["percentage"] == 16.67


async def test_cancelled_attempt_cannot_be_cancelled_or_submitted_again(client, learner, skill):
    headers = learner["headers"]
    attempt = await start_attempt(client, headers, skill["skill_id"])
    url = f"{API}/attempts/{attempt['attempt_id']}/cancel"

    assert (await client.patch(url, headers=headers)).status_code == 200
    detail = await client.get(f"{API}/attempts/{attempt['attempt_id']}", headers=headers)
    assert detail.json()["data"]["attempt"]["attempt_status"] == "cancelled"

    assert (await client.patch(url, headers=headers)).status_code == 400
    late = await submit(client, headers, attempt["attempt_id"], answers_for(attempt, skill))
    assert late.status_code == 409
