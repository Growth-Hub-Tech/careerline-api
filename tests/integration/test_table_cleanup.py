"""Day 28 table clean-up: the code no longer writes to the tables being retired."""

from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import take_test

API = settings.API_PREFIX


async def test_a_finished_test_writes_nothing_to_the_retired_tables(client, learner, skill, db):
    final = await take_test(client, learner["headers"], skill)
    assert final["answered"] == 16
    for table in (
        "learner_answer",
        "attempt_difficulty_score",
        "attempt_subskill_score",
        "learner_level",
    ):
        count = db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count == 0, f"{table} is being retired and must no longer be written"


async def test_the_answers_live_on_attempt_question(client, learner, skill, db):
    final = await take_test(client, learner["headers"], skill)
    answered = db.execute(
        text(
            "SELECT count(*) FROM attempt_question "
            "WHERE attempt_id = :id AND selected_option_id IS NOT NULL AND answered_at IS NOT NULL"
        ),
        {"id": final["attempt_id"]},
    ).scalar_one()
    assert answered == 16


async def test_levels_come_from_the_latest_skill_history_row(client, learner, skill):
    # a second test in the same skill replaces the level and never adds a row
    headers = learner["headers"]
    first = await take_test(client, headers, skill)
    second = await take_test(client, headers, skill, right=lambda info: False)
    assert first["result"]["level"] != second["result"]["level"]

    levels = (await client.get(f"{API}/recommendations/levels/me", headers=headers)).json()
    assert levels["data"]["confirmed_levels"] == [
        {"skill_id": skill["skill_id"], "skill_name": "Python", "level": second["result"]["level"]}
    ]


async def test_levels_are_empty_before_any_test(client, learner):
    levels = (
        await client.get(f"{API}/recommendations/levels/me", headers=learner["headers"])
    ).json()
    assert levels["data"]["confirmed_levels"] == []
