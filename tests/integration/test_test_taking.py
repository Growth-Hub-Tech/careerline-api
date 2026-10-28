"""Day 10: taking a test is real. One question at a time (never with the answer), harder or
easier with each answer, resume and expiry, and every finished test saved as a result and a
skill-history entry in one transaction. No pass or fail and no self-declared level."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

import app.services.test_taking_service as test_taking
from app.core.config import settings
from tests.integration.conftest import (
    answer,
    assert_error_envelope,
    option_for,
    start_attempt,
    take_test,
)

API = settings.API_PREFIX


def _status(db, attempt_id: int) -> str:
    return db.execute(
        text("SELECT attempt_status FROM test_attempt WHERE attempt_id = :id"), {"id": attempt_id}
    ).scalar_one()


async def test_a_test_serves_one_question_at_a_time_without_the_answer(client, learner, skill):
    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        # the self-declared level is retired: still accepted, and ignored
        json={"skill_id": skill["skill_id"], "declared_level": "ADVANCED"},
    )
    assert response.status_code == 200, response.text
    state = response.json()["data"]
    assert state["status"] == "in_progress" and state["resumed"] is False
    assert state["total_questions"] == 16 and state["answered"] == 0
    assert datetime.fromisoformat(state["expires_at"]) > datetime.now(UTC) + timedelta(minutes=25)
    question = state["question"]
    assert question["position"] == 1
    assert skill["questions"][question["question_id"]]["level"] == "JUNIOR"
    assert set(question) == {"position", "question_id", "question_text", "subskill_id", "options"}
    for option in question["options"]:
        assert set(option) == {"option_id", "option_text"}
    assert "correct" not in response.text and "declared_level" not in state


async def test_harder_after_a_right_answer_easier_after_a_wrong_one(client, learner, skill):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    levels = []
    for right in (True, True, False, False, False):
        question_id = state["question"]["question_id"]
        levels.append(skill["questions"][question_id]["level"])
        response = await answer(
            client, headers, state["attempt_id"], question_id, option_for(skill, question_id, right)
        )
        state = response.json()["data"]
        assert "is_correct" not in response.text and "correct_option" not in response.text
    levels.append(skill["questions"][state["question"]["question_id"]]["level"])
    assert levels == ["JUNIOR", "MID", "ADVANCED", "MID", "JUNIOR", "BEGINNER"]
    assert state["answered"] == 5 and state["question"]["position"] == 6


async def test_a_finished_test_is_saved_as_a_result_and_a_skill_history_entry(
    client, learner, skill, db
):
    final = await take_test(client, learner["headers"], skill)
    assert final["status"] == "completed" and final["question"] is None
    result = final["result"]
    assert result["level"] == "ADVANCED" and result["score"] >= 81
    assert result["answered"] == 16 and result["correct"] == 16
    assert 0 <= result["confidence"] <= 1 and result["confidence_label"] in {
        "low",
        "medium",
        "high",
    }
    assert result["ended_by"] == "finished"
    assert {s["subskill_name"] for s in result["subskills"]} == {"Lists", "Functions"}
    assert "passed" not in result and "status" not in result

    attempt = db.execute(
        text(
            "SELECT attempt_status, overall_percentage, end_time IS NOT NULL, "
            "declared_level_id FROM test_attempt WHERE attempt_id = :id"
        ),
        {"id": final["attempt_id"]},
    ).one()
    assert attempt[0] == "COMPLETED" and float(attempt[1]) == result["score"] and attempt[2]
    assert attempt[3] is None  # no self-declared level
    history = db.execute(
        text("SELECT level::text, score, attempt_id FROM skill_history WHERE learner_id = :id"),
        {"id": learner["learner_id"]},
    ).all()
    assert history == [("ADVANCED", result["score"], final["attempt_id"])]


async def test_the_attempt_page_shows_the_result(client, learner, skill):
    final = await take_test(client, learner["headers"], skill, right=lambda info: False)
    detail = await client.get(f"{API}/attempts/{final['attempt_id']}", headers=learner["headers"])
    attempt = detail.json()["data"]["attempt"]
    assert attempt["attempt_status"] == "completed"
    assert attempt["overall_percentage"] == final["result"]["score"]
    assert attempt["result"]["level"] == "BEGINNER"


async def test_starting_again_resumes_the_test_in_progress(client, learner, skill):
    headers = learner["headers"]
    first = await start_attempt(client, headers, skill["skill_id"])
    question_id = first["question"]["question_id"]
    await answer(
        client, headers, first["attempt_id"], question_id, option_for(skill, question_id, True)
    )

    again = await start_attempt(client, headers, skill["skill_id"])
    assert again["attempt_id"] == first["attempt_id"] and again["resumed"] is True
    assert again["answered"] == 1 and again["question"]["position"] == 2

    current = await client.get(f"{API}/attempts/{first['attempt_id']}/question", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["data"]["question"] == again["question"]


async def test_only_the_current_question_can_be_answered_once(client, learner, skill):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    question_id = state["question"]["question_id"]
    other = next(q for q in skill["questions"] if q != question_id)
    wrong_question = await answer(
        client, headers, state["attempt_id"], other, option_for(skill, other, True)
    )
    assert_error_envelope(wrong_question, 409, "not_current_question")

    ok = await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
    )
    assert ok.status_code == 200
    replay = await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
    )
    assert_error_envelope(replay, 409, "not_current_question")


async def test_an_option_of_another_question_is_400(client, learner, skill):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    question_id = state["question"]["question_id"]
    other = next(q for q in skill["questions"] if q != question_id)
    response = await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, other, True)
    )
    assert_error_envelope(response, 400, "bad_request")


async def test_an_expired_test_with_few_answers_has_no_result(client, learner, skill, database, db):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    with database.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_attempt SET expires_at = now() - interval '1 minute' WHERE attempt_id = :id"
            ),
            {"id": state["attempt_id"]},
        )
    question_id = state["question"]["question_id"]
    late = await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
    )
    error = assert_error_envelope(late, 410, "expired")
    assert error["details"] == {"status": "expired"}
    assert _status(db, state["attempt_id"]) == "EXPIRED"
    assert db.execute(text("SELECT count(*) FROM skill_history")).scalar_one() == 0

    # a new start begins a new test
    fresh = await start_attempt(client, headers, skill["skill_id"])
    assert fresh["attempt_id"] != state["attempt_id"] and fresh["resumed"] is False


async def test_an_expired_test_with_enough_answers_is_scored(client, learner, skill, database, db):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    for _ in range(settings.ADAPTIVE_MIN_ANSWERS_FOR_RESULT):
        question_id = state["question"]["question_id"]
        response = await answer(
            client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
        )
        state = response.json()["data"]
    with database.begin() as conn:
        conn.execute(
            text(
                "UPDATE test_attempt SET expires_at = now() - interval '1 minute' WHERE attempt_id = :id"
            ),
            {"id": state["attempt_id"]},
        )
    current = await client.get(f"{API}/attempts/{state['attempt_id']}/question", headers=headers)
    data = current.json()["data"]
    assert data["status"] == "completed" and data["question"] is None
    assert data["result"]["ended_by"] == "time_up"
    assert data["result"]["answered"] == settings.ADAPTIVE_MIN_ANSWERS_FOR_RESULT
    assert _status(db, state["attempt_id"]) == "COMPLETED"
    assert db.execute(text("SELECT count(*) FROM skill_history")).scalar_one() == 1


async def test_result_and_history_are_saved_together_or_not_at_all(
    client, learner, skill, db, monkeypatch
):
    async def broken(*args, **kwargs):
        raise RuntimeError("database went away while saving the history")

    monkeypatch.setattr(test_taking, "save_skill_history", broken)
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    for _ in range(16):
        question_id = state["question"]["question_id"]
        response = await answer(
            client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
        )
        if response.status_code != 200:
            break
        state = response.json()["data"]
    assert response.status_code == 500
    assert _status(db, state["attempt_id"]) == "IN_PROGRESS"
    assert db.execute(text("SELECT count(*) FROM skill_history")).scalar_one() == 0
    answered = db.execute(
        text(
            "SELECT count(*) FROM attempt_question WHERE attempt_id = :id AND answered_at IS NOT NULL"
        ),
        {"id": state["attempt_id"]},
    ).scalar_one()
    assert answered == 15  # the last answer was rolled back with the result


async def test_a_new_test_starts_at_the_level_the_person_reached(client, learner, skill):
    await take_test(client, learner["headers"], skill)  # ADVANCED
    state = await start_attempt(client, learner["headers"], skill["skill_id"])
    assert skill["questions"][state["question"]["question_id"]]["level"] == "ADVANCED"


async def test_another_learner_cannot_read_or_answer_my_test(client, learner, other_learner, skill):
    state = await start_attempt(client, learner["headers"], skill["skill_id"])
    question_id = state["question"]["question_id"]
    theirs = await answer(
        client,
        other_learner["headers"],
        state["attempt_id"],
        question_id,
        option_for(skill, question_id, True),
    )
    assert_error_envelope(theirs, 403, "forbidden")
    peek = await client.get(
        f"{API}/attempts/{state['attempt_id']}/question", headers=other_learner["headers"]
    )
    assert_error_envelope(peek, 403, "forbidden")


async def test_the_old_pass_fail_submit_is_retired(client, learner, skill):
    state = await start_attempt(client, learner["headers"], skill["skill_id"])
    response = await client.post(
        f"{API}/attempts/submit",
        headers=learner["headers"],
        json={"attempt_id": state["attempt_id"], "answers": []},
    )
    error = assert_error_envelope(response, 410, "gone")
    assert "/answer" in error["message"]


async def test_my_skill_profile_and_history(client, learner, skill):
    headers = learner["headers"]
    first = await take_test(client, headers, skill, right=lambda info: False)
    second = await take_test(client, headers, skill)

    profile = await client.get(f"{API}/profile/skills", headers=headers)
    assert profile.status_code == 200, profile.text
    assert "X-Sample-Data" not in profile.headers
    skills = profile.json()["data"]["skills"]
    assert skills == [
        {
            "skill_id": skill["skill_id"],
            "skill_name": "Python",
            "level": second["result"]["level"],
            "percentage_score": float(second["result"]["score"]),
            "confirmed_at": skills[0]["confirmed_at"],
        }
    ]

    history = await client.get(f"{API}/profile/skills/history", headers=headers)
    entries = history.json()["data"]["entries"]
    assert [e["attempt_id"] for e in entries] == [second["attempt_id"], first["attempt_id"]]
    assert entries[1]["level"] == "BEGINNER"
    assert set(entries[0]) == {
        "attempt_id",
        "skill_id",
        "skill_name",
        "level",
        "score",
        "confidence",
        "strengths",
        "weaknesses",
        "recorded_at",
    }
    only_python = await client.get(
        f"{API}/profile/skills/history", headers=headers, params={"skill_id": 999}
    )
    assert only_python.json()["data"]["entries"] == []
