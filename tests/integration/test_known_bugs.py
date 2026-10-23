"""Open bugs, written as tests of the CORRECT behaviour and marked xfail(strict=True).

Today each one fails, so pytest shows "xfailed" and the run stays green. When a later change
fixes the bug, the test passes, pytest reports "XPASS(strict)" and the run turns red: that is
the reminder to delete the xfail mark (and move the test next to its friends) so the fix stays
locked in.
"""

import time

import pytest

import app.services.scoring_service as scoring_service
from app.core.config import settings
from tests.integration.conftest import (
    answers_for,
    start_attempt,
    submit,
)

API = settings.API_PREFIX


@pytest.mark.xfail(
    strict=True,
    reason="Bug: submit calls OpenAI once per weak subskill, synchronously, inside the request "
    "(a blocking call in an async route, so the whole server waits). "
    "Day 5 moves the AI work to a background job.",
)
async def test_submit_does_not_wait_for_the_ai(client, learner, skill, monkeypatch):
    calls = []

    def slow_ai(skill_name, subskill_name, level_name, score):
        calls.append(subskill_name)
        time.sleep(1)  # pretend OpenAI is slow
        return "AI advice"

    # raising=False keeps this test meaningful after the old function is removed
    monkeypatch.setattr(scoring_service, "get_ai_benchmark", slow_ai, raising=False)
    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])

    started = time.monotonic()
    response = await submit(
        client, learner["headers"], attempt["attempt_id"], answers_for(attempt, skill, set())
    )
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert calls == [], f"submit called the AI {len(calls)} time(s) inside the request"
    assert elapsed < 1.0, f"submit took {elapsed:.1f}s waiting for the AI"
