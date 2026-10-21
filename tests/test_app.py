from types import SimpleNamespace

from app.api.deps import get_db
from app.api.routes import api_router
from app.core.config import settings
from app.main import app


class FakeSession:
    """Stands in for AsyncSession: every query returns no rows."""

    async def execute(self, *args, **kwargs):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


class BrokenSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("connection to db failed: password=hunter2")


def use_session(session_cls):
    async def override():
        yield session_cls()

    app.dependency_overrides[get_db] = override


async def test_healthz_returns_the_success_envelope(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": f"{settings.APP_NAME} is running",
        "data": {"status": "healthy"},
    }


async def test_api_routes_are_mounted_under_the_global_prefix(client):
    paths = app.openapi()["paths"]
    route_paths = [route.path for route in api_router.routes]

    # Route files never repeat the prefix; app/main.py adds it once for all of them
    assert not any(path.startswith(settings.API_PREFIX) for path in route_paths)
    assert all(settings.API_PREFIX + path in paths for path in route_paths)
    assert (await client.get("/skills/")).status_code == 404


async def test_route_data_is_wrapped_in_the_success_envelope(client):
    use_session(FakeSession)

    response = await client.get(f"{settings.API_PREFIX}/skills/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": None,
        "data": {"total": 0, "limit": 10, "offset": 0, "skills": []},
    }


async def test_unknown_route_returns_the_error_envelope_with_a_request_id(client):
    response = await client.get(f"{settings.API_PREFIX}/does-not-exist")

    body = response.json()
    assert response.status_code == 404
    assert body["success"] is False
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]


async def test_validation_errors_never_echo_submitted_values(client):
    response = await client.post(
        f"{settings.API_PREFIX}/auth/register",
        json={"email": "someone@example.com", "password": "SuperSecret123"},
    )

    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "validation_error"
    assert {tuple(d["loc"]) for d in body["error"]["details"]} == {
        ("body", "full_name"),
        ("body", "phone"),
    }
    assert "SuperSecret123" not in response.text
    assert "someone@example.com" not in response.text


async def test_unhandled_errors_return_a_generic_500_without_internals(client):
    use_session(BrokenSession)

    response = await client.get(f"{settings.API_PREFIX}/skills/")

    body = response.json()
    assert response.status_code == 500
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "Something went wrong. Please try again later."
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "hunter2" not in response.text


async def test_missing_token_gives_401_with_www_authenticate(client):
    response = await client.get(f"{settings.API_PREFIX}/learners/1")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_a_valid_inbound_request_id_is_reused(client):
    response = await client.get("/healthz", headers={"X-Request-ID": "frontend-abc.123"})

    assert response.headers["X-Request-ID"] == "frontend-abc.123"


async def test_an_unsafe_inbound_request_id_is_replaced(client):
    response = await client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})

    assert response.headers["X-Request-ID"] != "bad id\nwith newline"
    assert len(response.headers["X-Request-ID"]) == 32


async def test_security_headers_are_set(client):
    response = await client.get("/healthz")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_login_keeps_the_standard_oauth2_token_body():
    login = app.openapi()["paths"][f"{settings.API_PREFIX}/auth/login"]["post"]

    schema = login["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/TokenResponse"}
