import pytest

from app.core.config import settings
from app.core.security import create_access_token

API = settings.API_PREFIX


@pytest.fixture(autouse=True)
def sample_state(tmp_path, monkeypatch):
    """Every test gets its own empty sample state (payments, invitations, ...)."""
    monkeypatch.setattr(settings, "SAMPLE_STATE_FILE", str(tmp_path / "sample-state.json"))


@pytest.fixture
def auth() -> dict[str, str]:
    """A real login token. Sample routes check it but never look the account up (no database)."""
    return {"Authorization": f"Bearer {create_access_token(1)}"}


@pytest.fixture
def other_auth() -> dict[str, str]:
    """A second person (e.g. the candidate a recruiter invites)."""
    return {"Authorization": f"Bearer {create_access_token(2)}"}


def assert_sample(response, status: int = 200) -> dict:
    """A sample success: right status, the sample marker header and message, returns data."""
    assert response.status_code == status, response.text
    assert response.headers["X-Sample-Data"] == "true"
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Sample data"
    return body["data"]


def assert_sample_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["X-Sample-Data"] == "true"
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    return body["error"]
