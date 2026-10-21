import os

# Settings are read at import time, so these must be set before the app is imported.
# No database is needed: nothing here connects (the engine connects lazily).
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/careerline_test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-used-anywhere-else")
os.environ["CHECK_MIGRATIONS_ON_STARTUP"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
