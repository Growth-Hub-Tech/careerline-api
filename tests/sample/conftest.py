import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.api.deps import current_membership, optional_current_session
from app.core.config import settings
from app.core.security import create_access_token, decode_token
from app.main import app
from app.sample.routes.organisations import ORG_ID

API = settings.API_PREFIX


@pytest.fixture(autouse=True)
def sample_state(tmp_path, monkeypatch):
    """Every test gets its own empty sample state (payments, invitations, ...)."""
    monkeypatch.setattr(settings, "SAMPLE_STATE_FILE", str(tmp_path / "sample-state.json"))


# The sample tests run without a database. Since Day 6/7 the app looks the session and the
# organisation role up in the database; here a signed token stands in for an open session, and
# every signed-in person is an owner of the sample organisation. The real lookups and the
# access rules are tested in tests/integration (test_sessions.py, test_route_access.py).
async def _session_from_token(request: Request):
    scheme, _, token = (request.headers.get("Authorization") or "").partition(" ")
    decoded = decode_token(token) if scheme.lower() == "bearer" and token else None
    if decoded is None:
        return None
    learner = SimpleNamespace(learner_id=decoded[0], is_active=True)
    return SimpleNamespace(learner=learner, session=SimpleNamespace(id=decoded[1]))


async def _sample_owner(current=None, request: Request = None):  # type: ignore[assignment]
    current = await _session_from_token(request) if request is not None else None
    if current is None:
        return None
    return SimpleNamespace(
        organisation_id=ORG_ID,
        learner_id=current.learner.learner_id,
        role="owner",
        created_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def no_database_for_sessions():
    app.dependency_overrides[optional_current_session] = _session_from_token
    app.dependency_overrides[current_membership] = _sample_owner
    yield
    app.dependency_overrides.pop(optional_current_session, None)
    app.dependency_overrides.pop(current_membership, None)


def _token(learner_id: int) -> str:
    return create_access_token(learner_id, session_id=str(uuid.uuid4()))


@pytest.fixture
def auth() -> dict[str, str]:
    """A signed-in learner 1 (an owner of the sample organisation, see above)."""
    return {"Authorization": f"Bearer {_token(1)}"}


@pytest.fixture
def other_auth() -> dict[str, str]:
    """A second person (e.g. the candidate a recruiter invites)."""
    return {"Authorization": f"Bearer {_token(2)}"}


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
