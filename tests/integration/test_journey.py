from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import answer, option_for, start_attempt, take_test

API = settings.API_PREFIX


async def test_full_learner_journey(client, learner, skill, db):
    headers = learner["headers"]
    lists_id, functions_id = skill["subskill_ids"]

    # 1. Skills and subskills
    skills = (await client.get(f"{API}/skills/")).json()["data"]
    assert skills["total"] == 1
    assert skills["skills"][0]["skill_name"] == "Python"
    assert skills["skills"][0]["testable"] is True
    subskills = (await client.get(f"{API}/skills/{skill['skill_id']}/subskills")).json()["data"]
    assert subskills["total_subskills"] == 2

    # 2. The adaptive test: every Lists answer right, every Functions answer wrong
    final = await take_test(
        client, headers, skill, right=lambda info: info["subskill_id"] == lists_id
    )
    result = final["result"]
    assert final["answered"] == final["total_questions"] == 16
    assert [s["subskill_id"] for s in result["strengths"]] == [lists_id]
    assert [s["subskill_id"] for s in result["weaknesses"]] == [functions_id]
    assert result["weaknesses"][0]["subskill_name"] == "Functions"
    by_id = {s["subskill_id"]: s for s in result["subskills"]}
    assert by_id[lists_id]["band"] == "strong" and by_id[functions_id]["band"] == "weak"
    assert by_id[lists_id]["percentage_score"] == 100.0
    assert by_id[functions_id]["percentage_score"] == 0.0

    # 3. Recommendations: only the weak subskill, from the fallback text (no OpenAI key in tests)
    recommendations = final["recommendations"]
    assert recommendations["total_weak_areas"] == 1
    weak = recommendations["recommendations"][0]
    assert weak["subskill_id"] == functions_id
    assert weak["recommendation"].startswith("Dedicate focused time to Functions")

    # 4. The result can be read back
    detail = (await client.get(f"{API}/attempts/{final['attempt_id']}", headers=headers)).json()
    assert detail["data"]["attempt"]["attempt_status"] == "completed"
    assert detail["data"]["attempt"]["overall_percentage"] == result["score"]

    history = await client.get(f"{API}/attempts/me", headers=headers)
    assert [a["attempt_id"] for a in history.json()["data"]["attempts"]] == [final["attempt_id"]]

    pathway = await client.get(
        f"{API}/recommendations/pathway/me/{skill['skill_id']}", headers=headers
    )
    assert pathway.status_code == 200
    steps = pathway.json()["data"]["learning_pathway"]
    assert [step["subskill_name"] for step in steps] == ["Functions"]

    # 5. The level the test gave is the person's level for that skill
    levels = await client.get(f"{API}/recommendations/levels/me", headers=headers)
    assert levels.json()["data"]["confirmed_levels"] == [
        {"skill_id": skill["skill_id"], "skill_name": "Python", "level": result["level"]}
    ]
    row = db.execute(
        text("SELECT skill_id, attempt_id FROM learner_level WHERE learner_id = :id"),
        {"id": learner["learner_id"]},
    ).one()
    assert tuple(row) == (skill["skill_id"], final["attempt_id"])


async def test_all_right_needs_no_recommendations(client, learner, skill):
    final = await take_test(client, learner["headers"], skill)
    assert final["result"]["weaknesses"] == []
    assert final["recommendations"]["recommendations"] == []


async def test_a_finished_test_takes_no_more_answers(client, learner, skill):
    headers = learner["headers"]
    final = await take_test(client, headers, skill)
    question_id = next(iter(skill["questions"]))
    late = await answer(
        client, headers, final["attempt_id"], question_id, option_for(skill, question_id, True)
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "attempt_finished"


async def test_cancelled_attempt_cannot_be_cancelled_or_answered_again(client, learner, skill):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    url = f"{API}/attempts/{state['attempt_id']}/cancel"

    assert (await client.patch(url, headers=headers)).status_code == 200
    detail = await client.get(f"{API}/attempts/{state['attempt_id']}", headers=headers)
    assert detail.json()["data"]["attempt"]["attempt_status"] == "cancelled"

    assert (await client.patch(url, headers=headers)).status_code == 400
    question_id = state["question"]["question_id"]
    late = await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
    )
    assert late.status_code == 409
    # a cancelled test is not resumed: starting again begins a new one
    fresh = await start_attempt(client, headers, skill["skill_id"])
    assert fresh["attempt_id"] != state["attempt_id"]
