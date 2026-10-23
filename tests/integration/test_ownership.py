import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import answers_for, start_attempt, submit

API = settings.API_PREFIX


@pytest.fixture
async def owned_attempt(client, learner, skill) -> dict:
    """An in-progress attempt that belongs to `learner`."""
    return await start_attempt(client, learner["headers"], skill["skill_id"])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/attempts/{attempt_id}"),
        ("PATCH", "/attempts/{attempt_id}/cancel"),
        ("GET", "/attempts/learner/{learner_id}"),
        ("GET", "/learners/{learner_id}"),
        ("GET", "/recommendations/levels/{learner_id}"),
        ("GET", "/recommendations/pathway/{learner_id}/{skill_id}"),
    ],
)
async def test_another_learner_gets_403(
    client, learner, other_learner, skill, owned_attempt, method, path
):
    url = API + path.format(
        attempt_id=owned_attempt["attempt_id"],
        learner_id=learner["learner_id"],
        skill_id=skill["skill_id"],
    )

    response = await client.request(method, url, headers=other_learner["headers"])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_another_learner_cannot_submit_my_attempt(
    client, learner, other_learner, skill, owned_attempt, db
):
    response = await submit(
        client,
        other_learner["headers"],
        owned_attempt["attempt_id"],
        answers_for(owned_attempt, skill),
    )

    assert response.status_code == 403
    status = db.execute(
        text("SELECT attempt_status FROM test_attempt WHERE attempt_id = :id"),
        {"id": owned_attempt["attempt_id"]},
    ).scalar_one()
    assert status == "IN_PROGRESS"
    # ...and the owner can still submit it
    mine = await submit(
        client, learner["headers"], owned_attempt["attempt_id"], answers_for(owned_attempt, skill)
    )
    assert mine.status_code == 200


async def test_attempt_is_created_for_the_learner_in_the_token(client, learner, skill, db):
    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])

    owner = db.execute(
        text("SELECT learner_id FROM test_attempt WHERE attempt_id = :id"),
        {"id": attempt["attempt_id"]},
    ).scalar_one()
    assert owner == learner["learner_id"]
