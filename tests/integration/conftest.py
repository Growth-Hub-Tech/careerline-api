"""Fixtures for the integration tests: a real PostgreSQL test database, migrated with Alembic.

These tests only run when TEST_DATABASE_URL is set (tests/conftest.py checks that it is a local
test database first). The database is created if it does not exist, migrated to head once per
run, and every table is emptied before each test, so no test can see another test's rows.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db import seed
from app.db.session import engine as app_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct-horse-battery"


def _create_database_if_missing(url: str) -> None:
    target = make_url(url)
    maintenance = create_engine(
        target.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        with maintenance.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        maintenance.dispose()


@pytest.fixture(scope="session")
def database() -> Engine:
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("set TEST_DATABASE_URL to run the database tests (see README, Testing)")

    _create_database_if_missing(settings.sync_database_url)

    # Same migrations as production: an empty database goes to head
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(alembic_cfg, "head")

    sync_engine = create_engine(settings.sync_database_url, poolclass=NullPool)
    yield sync_engine
    sync_engine.dispose()


@pytest.fixture(autouse=True)
async def clean_database(database: Engine):
    with database.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalars()
        names = ", ".join(f'"{name}"' for name in tables)
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        # Reference data the app expects: the 4 levels and their score bands, from the seed
        # files (tests add their own small skill; test_seeds.py loads the whole question bank)
        seed.load(conn, tables=seed.LEVEL_TABLES)
    yield
    # Each test has its own event loop; close the app's pooled connections before it ends
    await app_engine.dispose()


@pytest.fixture
def db(database: Engine):
    """A plain (sync) connection for checking rows directly in the test database."""
    with database.connect() as conn:
        yield conn


@pytest.fixture
def skill(database: Engine) -> dict:
    """One skill with 2 subskills, each with 3 JUNIOR questions of 3 options (1 correct)."""
    questions: dict[int, dict] = {}
    with database.begin() as conn:
        skill_id = conn.execute(
            text(
                "INSERT INTO skills (skill_name, category, skill_descr) "
                "VALUES ('Python', 'Programming', 'Python basics') RETURNING skill_id"
            )
        ).scalar_one()
        subskill_ids = []
        for name in ("Lists", "Functions"):
            subskill_id = conn.execute(
                text(
                    "INSERT INTO subskills (skill_id, subskill_name) "
                    "VALUES (:skill_id, :name) RETURNING subskill_id"
                ),
                {"skill_id": skill_id, "name": name},
            ).scalar_one()
            subskill_ids.append(subskill_id)
            for number in range(1, 4):
                question_id = conn.execute(
                    text(
                        "INSERT INTO questions (subskill_id, question_text, difficulty_level, weight) "
                        "VALUES (:subskill_id, :text, 'JUNIOR', 1) RETURNING question_id"
                    ),
                    {"subskill_id": subskill_id, "text": f"{name} question {number}"},
                ).scalar_one()
                option_ids = [
                    conn.execute(
                        text(
                            "INSERT INTO options (question_id, option_text, is_correct) "
                            "VALUES (:question_id, :text, :correct) RETURNING option_id"
                        ),
                        {"question_id": question_id, "text": f"option {i}", "correct": i == 0},
                    ).scalar_one()
                    for i in range(3)
                ]
                questions[question_id] = {
                    "subskill_id": subskill_id,
                    "correct": option_ids[0],
                    "wrong": option_ids[1:],
                }
    return {"skill_id": skill_id, "subskill_ids": subskill_ids, "questions": questions}


async def register(client, email: str, password: str = PASSWORD, full_name: str = "Test Learner"):
    return await client.post(
        f"{settings.API_PREFIX}/auth/register",
        json={"full_name": full_name, "email": email, "phone": "08000000000", "password": password},
    )


async def login(client, email: str, password: str = PASSWORD):
    # OAuth2 password form: the email goes in "username"
    return await client.post(
        f"{settings.API_PREFIX}/auth/login", data={"username": email, "password": password}
    )


async def _make_learner(client, email: str, full_name: str) -> dict:
    response = await register(client, email, full_name=full_name)
    assert response.status_code == 200, response.text
    token = (await login(client, email)).json()["access_token"]
    return {
        "learner_id": response.json()["data"]["learner_id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest.fixture
async def learner(client) -> dict:
    return await _make_learner(client, "ada@example.com", "Ada Learner")


@pytest.fixture
async def other_learner(client) -> dict:
    return await _make_learner(client, "bola@example.com", "Bola Learner")


async def start_attempt(client, headers: dict, skill_id: int, level: str = "JUNIOR") -> dict:
    response = await client.post(
        f"{settings.API_PREFIX}/attempts/start",
        headers=headers,
        json={"skill_id": skill_id, "declared_level": level},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def answers_for(attempt: dict, skill: dict, correct_subskills: set[int] | None = None) -> list:
    """An answer for every served question: right for correct_subskills, wrong for the rest.

    correct_subskills=None means answer everything correctly.
    """
    answers = []
    for question in attempt["questions"]:
        info = skill["questions"][question["question_id"]]
        right = correct_subskills is None or info["subskill_id"] in correct_subskills
        option_id = info["correct"] if right else info["wrong"][0]
        answers.append({"question_id": question["question_id"], "selected_option_id": option_id})
    return answers


async def submit(client, headers: dict, attempt_id: int, answers: list):
    return await client.post(
        f"{settings.API_PREFIX}/attempts/submit",
        headers=headers,
        json={"attempt_id": attempt_id, "answers": answers},
    )


def assert_error_envelope(response, status: int, code: str) -> dict:
    """Check the standard error body and return its "error" part."""
    assert response.status_code == status, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    return body["error"]
