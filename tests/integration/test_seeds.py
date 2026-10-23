"""Loading the seed files into a real database: complete, safe to run twice, never touches
learners' data."""

import os
import subprocess
import sys

from sqlalchemy import text

from app.core.config import settings
from app.db.seed import TABLES, load, read_seed_rows

API = settings.API_PREFIX


def _count(conn, table: str) -> int:
    return conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()


def test_loading_twice_is_safe(database):
    in_files = {name: len(rows) for name, rows in read_seed_rows().items()}

    with database.begin() as conn:
        first = load(conn)
    with database.begin() as conn:
        second = load(conn)
        counts = {name: _count(conn, name) for name in TABLES}

    # clean_database already added the 4 levels and their thresholds
    assert first["questions"].inserted == 4000 and first["options"].inserted == 16000
    assert first["proficiency_level"].inserted == 0
    for name in TABLES:
        assert second[name].inserted == 0 and second[name].updated == 0, name
        assert second[name].unchanged == in_files[name], name
    assert counts == in_files


def test_a_question_changed_in_the_database_is_put_back(database):
    with database.begin() as conn:
        load(conn)
        original = conn.execute(
            text("SELECT question_text FROM questions WHERE question_id = 1")
        ).scalar_one()
        conn.execute(
            text("UPDATE questions SET question_text = 'edited by hand' WHERE question_id = 1")
        )
    with database.begin() as conn:
        result = load(conn)
        restored = conn.execute(
            text("SELECT question_text FROM questions WHERE question_id = 1")
        ).scalar_one()
    assert result["questions"].updated == 1
    assert restored == original


def test_rows_created_after_loading_get_new_ids(database):
    with database.begin() as conn:
        load(conn)
        new_id = conn.execute(
            text("INSERT INTO skills (skill_name) VALUES ('Brand new skill') RETURNING skill_id")
        ).scalar_one()
    assert new_id > 50


async def test_loading_leaves_learners_and_attempts_alone(client, learner, skill, database):
    from tests.integration.conftest import start_attempt

    attempt = await start_attempt(client, learner["headers"], skill["skill_id"])
    with database.begin() as conn:
        before = {t: _count(conn, t) for t in ("learner", "test_attempt", "attempt_question")}
        load(conn)
        after = {t: _count(conn, t) for t in ("learner", "test_attempt", "attempt_question")}
    assert before == after and after["test_attempt"] == 1
    response = await client.get(
        f"{API}/attempts/{attempt['attempt_id']}", headers=learner["headers"]
    )
    assert response.status_code == 200, response.text


async def test_a_fresh_database_with_the_seeds_can_start_an_attempt(client, learner, database):
    """Was the Day 1 known bug "Level JUNIOR not found": nothing created the 4 levels."""
    with database.begin() as conn:
        # Back to what migrations alone give you: no reference data at all
        conn.exec_driver_sql("TRUNCATE proficiency_level, level_threshold CASCADE")
        load(conn)
        skill_id = conn.execute(
            text(
                "SELECT s.skill_id FROM skills s JOIN subskills ss USING (skill_id) "
                "JOIN questions q USING (subskill_id) WHERE q.difficulty_level = 'JUNIOR' LIMIT 1"
            )
        ).scalar_one()

    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": skill_id, "declared_level": "JUNIOR"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["questions"]


def test_the_command_line_loader(database):
    env = {**os.environ, "DATABASE_URL": settings.DATABASE_URL}
    for _ in range(2):
        run = subprocess.run(
            [sys.executable, "-m", "app.db.seed"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    assert "questions" in run.stdout
    last = [line.split() for line in run.stdout.splitlines() if line.startswith("questions")][0]
    assert last == ["questions", "4000", "0", "0", "4000"]
