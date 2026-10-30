"""Day 11: explanations of a finished test's answers.

After a test ends, GET /attempts/{id}/review shows every question with the right answer, the
person's choice and an explanation. The AI explanation is asked once per question in a
background job and kept for everyone; without an OpenAI key (or when the AI fails) each
explanation is a plain standard one. Nothing is shown while the test is still running.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

import app.integrations.openai_client as openai_client
from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import (
    answer,
    assert_error_envelope,
    option_for,
    start_attempt,
    take_test,
)

API = settings.API_PREFIX


def _review_url(attempt_id: int) -> str:
    return f"{API}/attempts/{attempt_id}/review"


async def _run_jobs() -> None:
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


@pytest.fixture
def fake_ai(monkeypatch):
    """A fake AI: records each question it is asked about. Never the real OpenAI."""
    calls: list[str] = []

    def explain(skill_name, subskill_name, question_text, options, correct_option):
        calls.append(question_text)
        return f"Because {correct_option} is right for: {question_text}"

    monkeypatch.setattr(openai_client, "explain_answer", explain)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-a-real-key")
    return calls


async def test_no_review_while_the_test_is_running(client, learner, skill):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    question_id = state["question"]["question_id"]
    await answer(
        client, headers, state["attempt_id"], question_id, option_for(skill, question_id, False)
    )

    response = await client.get(_review_url(state["attempt_id"]), headers=headers)
    assert_error_envelope(response, 409, "attempt_not_finished")
    assert "is_correct" not in response.text and "correct_option_id" not in response.text
    assert "explanation" not in response.text


async def test_a_finished_test_shows_every_answer_with_a_standard_explanation(
    client, learner, skill
):
    headers = learner["headers"]
    final = await take_test(
        client, headers, skill, right=lambda info: info["subskill_id"] == skill["subskill_ids"][0]
    )

    response = await client.get(_review_url(final["attempt_id"]), headers=headers)
    assert response.status_code == 200, response.text
    review = response.json()["data"]
    assert review["attempt_id"] == final["attempt_id"] and review["status"] == "completed"
    assert review["result"]["score"] == final["result"]["score"]
    assert review["ai_explanations"] == "unavailable"  # no OpenAI key in the tests
    items = review["items"]
    assert [item["position"] for item in items] == list(range(1, 17))
    for item in items:
        info = skill["questions"][item["question_id"]]
        assert item["correct_option_id"] == info["correct"]
        assert item["subskill_name"] in {"Lists", "Functions"}
        assert item["level"] == info["level"]
        chosen = [o["option_id"] for o in item["options"] if o["chosen"]]
        assert chosen == [item["selected_option_id"]]
        assert [o["option_id"] for o in item["options"] if o["is_correct"]] == [info["correct"]]
        assert item["is_correct"] is (item["selected_option_id"] == info["correct"])
        assert item["explanation_source"] == "standard"
        assert "option 0" in item["explanation"]  # names the right answer
        if not item["is_correct"]:
            assert "option 1" in item["explanation"]  # and the one chosen


async def test_review_options_are_in_the_order_the_question_was_shown(client, learner, skill):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    shown = [o["option_id"] for o in state["question"]["options"]]
    first_question = state["question"]["question_id"]
    final = await take_test(client, headers, skill)
    assert final["attempt_id"] == state["attempt_id"]

    review = (await client.get(_review_url(final["attempt_id"]), headers=headers)).json()["data"]
    item = next(i for i in review["items"] if i["question_id"] == first_question)
    assert [o["option_id"] for o in item["options"]] == shown


async def test_only_the_owner_sees_the_review(client, learner, other_learner, skill):
    final = await take_test(client, learner["headers"], skill)
    response = await client.get(_review_url(final["attempt_id"]), headers=other_learner["headers"])
    assert_error_envelope(response, 403, "forbidden")
    missing = await client.get(_review_url(999999), headers=learner["headers"])
    assert_error_envelope(missing, 404, "not_found")
    anonymous = await client.get(_review_url(final["attempt_id"]))
    assert anonymous.status_code == 401


async def test_an_expired_test_can_be_reviewed_unanswered_questions_included(
    client, learner, skill, db
):
    headers = learner["headers"]
    state = await start_attempt(client, headers, skill["skill_id"])
    question_id = state["question"]["question_id"]
    state = (
        await answer(
            client, headers, state["attempt_id"], question_id, option_for(skill, question_id, True)
        )
    ).json()["data"]
    db.execute(
        text("UPDATE test_attempt SET expires_at = :past WHERE attempt_id = :id"),
        {"past": datetime.now(UTC) - timedelta(minutes=1), "id": state["attempt_id"]},
    )
    db.commit()

    response = await client.get(_review_url(state["attempt_id"]), headers=headers)
    assert response.status_code == 200, response.text
    review = response.json()["data"]
    assert review["status"] == "expired" and review["result"] is None
    assert len(review["items"]) == 2
    unanswered = review["items"][1]
    assert unanswered["selected_option_id"] is None and unanswered["is_correct"] is False
    assert not any(o["chosen"] for o in unanswered["options"])
    assert "not answered" in unanswered["explanation"].lower()


async def test_the_end_of_a_test_queues_one_explanation_job(client, learner, skill, fake_ai, db):
    final = await take_test(client, learner["headers"], skill)
    jobs = db.execute(
        text("SELECT payload ->> 'attempt_id' FROM background_jobs WHERE kind = :kind"),
        {"kind": "answer_explanations"},
    ).all()
    assert jobs == [(str(final["attempt_id"]),)]
    assert fake_ai == []  # never inside the request


async def test_the_job_adds_ai_explanations_that_are_kept_for_everyone(
    client, learner, other_learner, skill, fake_ai
):
    final = await take_test(client, learner["headers"], skill)
    before = (await client.get(_review_url(final["attempt_id"]), headers=learner["headers"])).json()
    assert before["data"]["ai_explanations"] == "generating"
    assert {i["explanation_source"] for i in before["data"]["items"]} == {"standard"}

    await _run_jobs()
    review = (await client.get(_review_url(final["attempt_id"]), headers=learner["headers"])).json()
    data = review["data"]
    assert data["ai_explanations"] == "ready"
    for item in data["items"]:
        assert item["explanation_source"] == "ai"
        assert item["explanation"] == (
            f"Because option 0 is right for: {item['question_text']}"
        )
    assert len(fake_ai) == 16

    # Another person's test of the same skill reuses what is kept: only new questions are asked
    asked_before = set(fake_ai)
    second = await take_test(client, other_learner["headers"], skill)
    await _run_jobs()
    second_review = (
        await client.get(_review_url(second["attempt_id"]), headers=other_learner["headers"])
    ).json()["data"]
    assert second_review["ai_explanations"] == "ready"
    repeated = [q for q in fake_ai[16:] if q in asked_before]
    assert repeated == []


async def test_when_the_ai_fails_the_standard_explanation_stays(
    client, learner, skill, monkeypatch
):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(openai_client, "explain_answer", lambda *args: None)
    final = await take_test(client, learner["headers"], skill)
    await _run_jobs()

    data = (await client.get(_review_url(final["attempt_id"]), headers=learner["headers"])).json()[
        "data"
    ]
    assert data["ai_explanations"] == "unavailable"
    assert {i["explanation_source"] for i in data["items"]} == {"standard"}


async def test_a_changed_question_is_explained_again(client, learner, skill, fake_ai, db):
    final = await take_test(client, learner["headers"], skill)
    await _run_jobs()
    review = (await client.get(_review_url(final["attempt_id"]), headers=learner["headers"])).json()
    question_id = review["data"]["items"][0]["question_id"]
    db.execute(
        text("UPDATE questions SET question_text = 'Reworded question' WHERE question_id = :id"),
        {"id": question_id},
    )
    db.commit()

    stale = (await client.get(_review_url(final["attempt_id"]), headers=learner["headers"])).json()
    item = stale["data"]["items"][0]
    assert item["explanation_source"] == "standard"  # the kept one was for the old wording
    assert stale["data"]["ai_explanations"] == "generating"  # asked again in the background
    await _run_jobs()
    fresh = (await client.get(_review_url(final["attempt_id"]), headers=learner["headers"])).json()
    item = fresh["data"]["items"][0]
    assert item["explanation_source"] == "ai" and "Reworded question" in item["explanation"]
