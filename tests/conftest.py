import os

import pytest
from dotenv import dotenv_values

from tests.db_guard import UnsafeTestDatabase, check_test_database_url

# The integration tests (tests/integration) need a real, separate test database, given by
# TEST_DATABASE_URL. It is checked before anything connects, then the app is pointed at it.
# Without it those tests are skipped locally; in CI (CI=true) a missing URL is an error.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    try:
        check_test_database_url(
            TEST_DATABASE_URL, real_database_url=dotenv_values(".env").get("DATABASE_URL")
        )
    except UnsafeTestDatabase as exc:
        pytest.exit(f"Refusing to run tests: {exc}", returncode=4)
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
elif os.environ.get("CI"):
    pytest.exit("TEST_DATABASE_URL must be set in CI so the database tests run", returncode=4)

# Settings are read at import time, so these must be set before the app is imported.
# No database is needed: nothing here connects (the engine connects lazily).
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/careerline_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-anywhere-else")
os.environ["CHECK_MIGRATIONS_ON_STARTUP"] = "false"
# Tests never call OpenAI, even when a real key is in .env
os.environ["OPENAI_API_KEY"] = ""

import httpx  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
