import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import answer, option_for, start_attempt

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
        ("GET", "/attempts/{attempt_id}/question"),
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


async def test_another_learner_cannot_answer_my_attempt(
    client, learner, other_learner, skill, owned_attempt, db
):
    question_id = owned_attempt["question"]["question_id"]
    option_id = option_for(skill, question_id, True)
    response = await answer(
        client, other_learner["headers"], owned_attempt["attempt_id"], question_id, option_id
    )

    assert response.status_code == 403
    answered = db.execute(
        text(
            "SELECT count(*) FROM attempt_question WHERE attempt_id = :id AND answered_at IS NOT NULL"
        ),
        {"id": owned_attempt["attempt_id"]},
    ).scalar_one()
    assert answered == 0
    # ...and the owner can still answer it
    mine = await answer(
        client, learner["headers"], owned_attempt["attempt_id"], question_id, option_id
    )
    assert mine.status_code == 200


async def test_attempt_is_created_for_the_learner_in_the_token(client, learner, skill, db):
    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])

    owner = db.execute(
        text("SELECT learner_id FROM test_attempt WHERE attempt_id = :id"),
        {"id": attempt["attempt_id"]},
    ).scalar_one()
    assert owner == learner["learner_id"]
