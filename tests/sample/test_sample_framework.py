"""The rules every sample route follows: marked, scenario header, login, never shadows a real route."""

import pytest
from fastapi.routing import APIRoute

from app.api.routes import api_router
from app.core.config import settings
from app.main import app, create_app
from app.sample.core import ERROR_SCENARIO_STATUS
from app.sample.router import sample_router
from tests.sample.conftest import API, assert_sample, assert_sample_error


def _routes(router) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_no_sample_route_has_the_same_method_and_path_as_a_real_route():
    clashes = _routes(sample_router) & _routes(api_router)
    assert clashes == set(), f"sample routes shadow real ones: {sorted(clashes)}"


def test_every_sample_operation_is_marked_in_the_api_description():
    paths = app.openapi()["paths"]
    sample_paths = {API + path for _, path in _routes(sample_router)}
    assert sample_paths, "no sample routes are mounted"
    for path in sample_paths:
        for method, operation in paths[path].items():
            assert operation["x-sample"] is True, (method, path)
            assert operation["tags"][0].startswith("Sample: "), (method, path)
            assert "Sample data" in operation["description"], (method, path)
            assert "X-Mock-Scenario" in operation["description"], (method, path)


def test_real_operations_are_not_marked_as_sample():
    paths = app.openapi()["paths"]
    for _, path in _routes(api_router):
        for operation in paths[API + path].values():
            assert "x-sample" not in operation


async def test_a_sample_answer_carries_the_marker_header_and_message(client):
    data = assert_sample(await client.get(f"{API}/tests"))
    assert data["total"] > 0


async def test_real_routes_do_not_carry_the_marker(client):
    response = await client.get("/healthz")
    assert "X-Sample-Data" not in response.headers


async def test_the_frontend_may_read_the_marker_header(client):
    response = await client.get(f"{API}/tests", headers={"Origin": "http://localhost:5173"})
    assert "x-sample-data" in response.headers["Access-Control-Expose-Headers"].lower()


@pytest.mark.parametrize("name,status", sorted(ERROR_SCENARIO_STATUS.items()))
async def test_each_error_scenario_forces_its_status_and_error_envelope(client, auth, name, status):
    response = await client.get(f"{API}/payments", headers={**auth, "X-Mock-Scenario": name})
    codes = {"server_error": "internal_error", "unavailable": "service_unavailable"}
    assert_sample_error(response, status, codes.get(name, name))


async def test_scenario_codes_match_the_api_error_codes(client, auth):
    expected = {
        "unauthenticated": 401,
        "payment_required": 402,
        "forbidden": 403,
        "not_found": 404,
        "conflict": 409,
        "expired": 410,
        "validation_error": 422,
        "rate_limited": 429,
        "server_error": 500,
        "unavailable": 503,
    }
    assert ERROR_SCENARIO_STATUS == expected


async def test_unavailable_and_unauthenticated_use_the_standard_error_codes(client, auth):
    response = await client.get(
        f"{API}/payments", headers={**auth, "X-Mock-Scenario": "unavailable"}
    )
    assert response.json()["error"]["code"] == "service_unavailable"
    response = await client.get(f"{API}/payments", headers={"X-Mock-Scenario": "unauthenticated"})
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_rate_limited_says_when_to_retry(client, auth):
    response = await client.get(
        f"{API}/payments", headers={**auth, "X-Mock-Scenario": "rate_limited"}
    )
    assert response.headers["Retry-After"] == "30"


async def test_the_empty_scenario_empties_lists(client, auth):
    data = assert_sample(
        await client.get(f"{API}/payments", headers={**auth, "X-Mock-Scenario": "empty"})
    )
    assert data == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_scenario_names_ignore_case_and_spaces(client, auth):
    response = await client.get(f"{API}/payments", headers={**auth, "X-Mock-Scenario": " Empty "})
    assert assert_sample(response)["items"] == []


async def test_an_unknown_scenario_is_a_400_that_lists_the_valid_ones(client, auth):
    response = await client.get(f"{API}/payments", headers={**auth, "X-Mock-Scenario": "emtpy"})
    error = assert_sample_error(response, 400, "bad_request")
    assert "empty" in error["message"]


async def test_a_scenario_the_route_does_not_offer_is_a_400(client, auth):
    # "empty" makes no sense for one payment
    response = await client.get(
        f"{API}/payments/made-up-reference", headers={**auth, "X-Mock-Scenario": "empty"}
    )
    assert_sample_error(response, 400, "bad_request")


async def test_the_offered_scenarios_are_listed_in_the_api_description():
    operation = app.openapi()["paths"][f"{API}/payments"]["get"]
    assert "empty" in operation["x-sample-scenarios"]
    assert "payment_required" in operation["x-sample-scenarios"]


async def test_protected_sample_routes_need_a_login_token(client):
    response = await client.get(f"{API}/payments")
    assert_sample_error(response, 401, "unauthenticated")
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_a_forged_token_is_refused(client):
    response = await client.get(
        f"{API}/payments", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert_sample_error(response, 401, "unauthenticated")


async def test_protected_sample_routes_use_the_real_login_in_the_api_description():
    operation = app.openapi()["paths"][f"{API}/payments"]["get"]
    assert operation["security"] == [{"OAuth2PasswordBearer": []}]


async def test_body_validation_on_sample_routes_uses_the_error_envelope(client):
    response = await client.post(f"{API}/payments/webhooks/paystack", json={"event": 42})
    assert_sample_error(response, 422, "validation_error")


def test_the_sample_api_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "SAMPLE_API_ENABLED", False)
    paths = create_app().openapi()["paths"]
    assert f"{API}/tests" not in paths
    assert f"{API}/skills/" in paths


def test_the_sample_api_is_off_in_production_unless_switched_on(monkeypatch):
    monkeypatch.setattr(settings, "SAMPLE_API_ENABLED", None)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    assert settings.sample_api_enabled is False
    monkeypatch.setattr(settings, "SAMPLE_API_ENABLED", True)
    assert settings.sample_api_enabled is True
    monkeypatch.setattr(settings, "SAMPLE_API_ENABLED", None)
    monkeypatch.setattr(settings, "APP_ENV", "staging")
    assert settings.sample_api_enabled is True
