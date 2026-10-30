"""Day 7: the person always comes from the session, never from the request.

Every learner route has a /me form that takes nobody's id. The older routes with a learner id
in the path still work for your own id (and are marked deprecated); the id in the body of
POST /learners/behavioural-answers is no longer needed and is ignored when it is yours.
"""

from app.core.config import settings
from app.main import app
from tests.integration.conftest import assert_error_envelope, start_attempt, take_test

API = settings.API_PREFIX


async def test_my_profile(client, learner):
    response = await client.get(f"{API}/learners/me", headers=learner["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["learner"]["learner_id"] == learner["learner_id"]


async def test_my_attempts_levels_and_pathway(client, learner, skill):
    lists_id = skill["subskill_ids"][0]
    attempt = await take_test(
        client, learner["headers"], skill, right=lambda info: info["subskill_id"] == lists_id
    )

    attempts = await client.get(f"{API}/attempts/me", headers=learner["headers"])
    assert attempts.status_code == 200, attempts.text
    assert [a["attempt_id"] for a in attempts.json()["data"]["attempts"]] == [attempt["attempt_id"]]

    levels = await client.get(f"{API}/recommendations/levels/me", headers=learner["headers"])
    assert levels.status_code == 200, levels.text
    assert levels.json()["data"]["learner_id"] == learner["learner_id"]

    pathway = await client.get(
        f"{API}/recommendations/pathway/me/{skill['skill_id']}", headers=learner["headers"]
    )
    assert pathway.status_code == 200, pathway.text
    assert len(pathway.json()["data"]["learning_pathway"]) == 1


async def test_me_routes_need_a_login(client):
    for path in (
        "learners/me",
        "attempts/me",
        "recommendations/levels/me",
        "recommendations/pathway/me/1",
    ):
        assert_error_envelope(await client.get(f"{API}/{path}"), 401, "unauthenticated")


async def test_behavioural_answers_take_the_learner_from_the_session(
    client, learner, other_learner, skill
):
    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])
    body = {"attempt_id": attempt["attempt_id"], "answers": []}
    response = await client.post(
        f"{API}/learners/behavioural-answers", headers=learner["headers"], json=body
    )
    assert response.status_code == 200, response.text

    # Someone else's id in the body is refused, never used
    response = await client.post(
        f"{API}/learners/behavioural-answers",
        headers=learner["headers"],
        json={**body, "learner_id": other_learner["learner_id"]},
    )
    assert_error_envelope(response, 403, "forbidden")


def test_the_routes_with_a_learner_id_are_deprecated_in_favour_of_me():
    paths = app.openapi()["paths"]
    for old, new in (
        ("/learners/{learner_id}", "/learners/me"),
        ("/attempts/learner/{learner_id}", "/attempts/me"),
        ("/recommendations/levels/{learner_id}", "/recommendations/levels/me"),
        (
            "/recommendations/pathway/{learner_id}/{skill_id}",
            "/recommendations/pathway/me/{skill_id}",
        ),
    ):
        assert paths[f"{API}{old}"]["get"].get("deprecated") is True, old
        assert "deprecated" not in paths[f"{API}{new}"]["get"], new
