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
    # Frontend Web Development is well stocked (every level has enough active questions)
    skill_id = 1

    response = await client.post(
        f"{API}/attempts/start", headers=learner["headers"], json={"skill_id": skill_id}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["question"]["options"]


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


def test_each_question_gets_its_status_and_issues_from_the_quality_check(database):
    with database.begin() as conn:
        load(conn)
        rows = conn.execute(
            text("SELECT status::text, count(*) FROM questions GROUP BY status")
        ).all()
        # question 1 ("What does HTML stand for?") is a good question
        first = conn.execute(
            text("SELECT status::text, quality_issues FROM questions WHERE question_id = 1")
        ).one()
        blocked = conn.execute(
            text(
                "SELECT count(*) FROM questions "
                "WHERE status = 'NEEDS_REVIEW' AND cardinality(quality_issues) = 0"
            )
        ).scalar_one()
    counts = dict(rows)
    assert counts["ACTIVE"] > 0 and counts["NEEDS_REVIEW"] > 0
    assert sum(counts.values()) == 4000
    assert first == ("ACTIVE", [])
    assert blocked == 0, "a question is never held back without a reason"


def test_job_roles_and_the_title_ladder_are_loaded(database):
    with database.begin() as conn:
        load(conn)
        roles = conn.execute(text("SELECT count(*) FROM job_roles")).scalar_one()
        role_skills = conn.execute(text("SELECT count(*) FROM job_role_skills")).scalar_one()
        ladder = conn.execute(
            text("SELECT slug, expected_level::text FROM job_titles ORDER BY rank")
        ).all()
    assert roles == 8 and role_skills >= 16
    assert [slug for slug, _ in ladder] == ["intern", "junior", "mid", "senior", "lead"]
    assert ladder[0][1] == "BEGINNER" and ladder[-1][1] == "ADVANCED"


def test_a_skill_removed_from_a_role_in_the_file_is_removed_from_the_role(database):
    with database.begin() as conn:
        load(conn)
        conn.execute(
            text(
                "INSERT INTO job_role_skills (role_id, skill_id, target_level, position) "
                "VALUES (101, 50, 'JUNIOR', 9)"
            )
        )
    with database.begin() as conn:
        load(conn)
        extra = conn.execute(
            text("SELECT count(*) FROM job_role_skills WHERE role_id = 101 AND skill_id = 50")
        ).scalar_one()
    assert extra == 0
