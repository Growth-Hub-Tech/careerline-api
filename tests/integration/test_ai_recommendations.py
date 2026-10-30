"""Day 5: the AI advice for weak subskills is a background job, not part of the request that
ends a test (since Day 10 the last answer; before, submit).

Before, submit called OpenAI once per weak subskill, synchronously, inside the request (a
blocking call in an async route, so the whole server waited). Now submit saves the plain advice
at once and queues one job per attempt; the job asks the AI and replaces the advice.
Tests never call OpenAI: get_ai_benchmark is replaced by a fake.
"""

import time

import pytest
from sqlalchemy import text

import app.integrations.openai_client as openai_client
import app.services.scoring_service as scoring_service
import app.services.test_taking_service as test_taking_service
from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import take_test

API = settings.API_PREFIX


def ai_jobs(db) -> int:
    return db.execute(
        text("SELECT count(*) FROM background_jobs WHERE kind = 'ai_recommendations'")
    ).scalar()


@pytest.fixture
def fake_ai(monkeypatch):
    calls: list[tuple] = []

    def slow_ai(skill_name, subskill_name, level_name, score):
        calls.append((skill_name, subskill_name, level_name, score))
        time.sleep(0.2)  # pretend OpenAI is slow
        return f"AI advice for {subskill_name}"

    monkeypatch.setattr(openai_client, "get_ai_benchmark", slow_ai)
    # raising=False: submit must not reach the AI through its old import either
    monkeypatch.setattr(scoring_service, "get_ai_benchmark", slow_ai, raising=False)
    monkeypatch.setattr(test_taking_service, "get_ai_benchmark", slow_ai, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-a-real-key")
    return calls


async def _fail_everything(client, learner, skill):
    final = await take_test(client, learner["headers"], skill, right=lambda info: False)
    return final, final


async def test_the_last_answer_does_not_wait_for_the_ai(client, learner, skill, fake_ai):
    started = time.monotonic()
    await _fail_everything(client, learner, skill)
    elapsed = time.monotonic() - started

    assert fake_ai == [], f"the test called the AI {len(fake_ai)} time(s) inside a request"
    assert elapsed < 5.0, f"16 answers took {elapsed:.1f}s: something waited for the AI"


async def test_the_end_of_a_test_gives_plain_advice_and_queues_one_ai_job(
    client, learner, skill, fake_ai, db
):
    attempt, result = await _fail_everything(client, learner, skill)

    recommendations = result["recommendations"]
    assert recommendations["total_weak_areas"] == 2
    assert recommendations["ai_advice"] == "queued"
    for item in recommendations["recommendations"]:
        assert item["recommendation"].startswith("Dedicate focused time to")

    jobs = db.execute(
        text(
            "SELECT kind, dedupe_key, payload FROM background_jobs WHERE kind = 'ai_recommendations'"
        )
    ).all()
    assert [(j.kind, j.dedupe_key) for j in jobs] == [
        ("ai_recommendations", f"ai-recommendations:attempt:{attempt['attempt_id']}")
    ]
    assert jobs[0].payload == {"attempt_id": attempt["attempt_id"]}


async def test_the_job_replaces_the_plain_advice_with_the_ai_advice(
    client, learner, skill, fake_ai
):
    attempt, _ = await _fail_everything(client, learner, skill)

    runner = JobRunner(worker_id="test")
    while await runner.run_once():  # the AI job (and the sign-up emails)
        pass
    assert sorted(call[1] for call in fake_ai) == ["Functions", "Lists"]

    response = await client.get(
        f"{API}/recommendations/pathway/{learner['learner_id']}/{skill['skill_id']}",
        headers=learner["headers"],
    )
    assert response.status_code == 200, response.text
    pathway = response.json()["data"]["learning_pathway"]
    assert sorted(step["recommendation"] for step in pathway) == [
        "AI advice for Functions",
        "AI advice for Lists",
    ]


async def test_without_an_openai_key_no_ai_job_is_queued(client, learner, skill, db, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    _, result = await _fail_everything(client, learner, skill)
    assert result["recommendations"]["ai_advice"] == "unavailable"
    assert ai_jobs(db) == 0


async def test_no_weak_subskills_means_no_ai_job(client, learner, skill, fake_ai, db):
    await take_test(client, learner["headers"], skill)
    assert ai_jobs(db) == 0
