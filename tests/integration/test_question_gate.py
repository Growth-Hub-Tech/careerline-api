"""Day 8: only ACTIVE questions are served, and a skill can be tested only when every level
has enough of them."""

from sqlalchemy import text

from app.core.config import settings
from app.db.seed import load
from tests.integration.conftest import assert_error_envelope, start_attempt

API = settings.API_PREFIX


async def test_questions_that_are_not_active_are_never_served(client, learner, skill, database):
    junior = [qid for qid, info in skill["questions"].items() if info["level"] == "JUNIOR"]
    held_back = junior[:2]
    with database.begin() as conn:
        conn.execute(
            text("UPDATE questions SET status = 'NEEDS_REVIEW' WHERE question_id = :a"),
            {"a": held_back[0]},
        )
        conn.execute(
            text("UPDATE questions SET status = 'RETIRED' WHERE question_id = :a"),
            {"a": held_back[1]},
        )
    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])
    served = {q["question_id"] for q in attempt["questions"]}
    assert served and not served & set(held_back)
    assert attempt["total_questions"] == 4


async def test_a_skill_short_of_active_questions_cannot_be_tested(
    client, learner, skill, database, monkeypatch
):
    monkeypatch.setattr(settings, "MIN_ACTIVE_QUESTIONS_PER_LEVEL", 6)
    mid = [qid for qid, info in skill["questions"].items() if info["level"] == "MID"]
    with database.begin() as conn:
        conn.execute(
            text("UPDATE questions SET status = 'NEEDS_REVIEW' WHERE question_id = :a"),
            {"a": mid[0]},
        )
    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": skill["skill_id"], "declared_level": "JUNIOR"},
    )
    error = assert_error_envelope(response, 409, "skill_not_ready")
    assert error["details"] == {"minimum_per_level": 6, "short_by": {"MID": 1}}
    with database.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM test_attempt")).scalar_one() == 0


async def test_the_skill_list_says_which_skills_can_be_tested(client, database):
    with database.begin() as conn:
        load(conn)
    body = (await client.get(f"{API}/skills/", params={"limit": 50})).json()["data"]
    testable = {s["skill_id"]: s["testable"] for s in body["skills"]}
    assert len(testable) == 50
    assert testable[1] is True  # Frontend Web Development: well stocked
    assert testable[13] is False  # UI/UX Design: most questions held back for review
    assert testable[41] is False  # Social Media Marketing: no questions yet
    assert 5 <= sum(testable.values()) <= 30


async def test_an_untestable_seeded_skill_is_refused(client, learner, database):
    with database.begin() as conn:
        load(conn)
    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": 41, "declared_level": "BEGINNER"},
    )
    error = assert_error_envelope(response, 409, "skill_not_ready")
    assert error["details"]["short_by"] == {"BEGINNER": 15, "JUNIOR": 15, "MID": 15, "ADVANCED": 15}
