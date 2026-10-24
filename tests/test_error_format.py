"""Day 5: every error has one format, a reference number, and no internal details.

The format: {"success": false, "error": {"code", "message", "request_id", "details"?}}.
request_id is the reference number: it is also in the X-Request-ID header and on every log line
for that request, so a user who quotes it lets us find the stack trace in the logs.
"""

import json
import logging

import pytest
from fastapi import APIRouter, HTTPException

from app.core.exceptions import AppError, ServiceUnavailableError
from app.main import app

INTERNALS = ("Traceback", 'File "', "RuntimeError", "asyncpg", "SELECT", "/srv/app", "password=")
SECRET_TEXT = 'asyncpg error in /srv/app/db.py: SELECT * FROM learner WHERE password="x"'


class _InternalAppError(AppError):
    status_code = 500
    code = "internal_error"


_router = APIRouter()


@_router.get("/__test__/crash")
async def _crash():
    raise RuntimeError(SECRET_TEXT)


@_router.get("/__test__/http-500")
async def _http_500():
    raise HTTPException(status_code=500, detail=SECRET_TEXT)


@_router.get("/__test__/app-500")
async def _app_500():
    raise _InternalAppError(SECRET_TEXT)


@_router.get("/__test__/unavailable")
async def _unavailable():
    raise ServiceUnavailableError("Service unavailable. Try again shortly.")


app.include_router(_router)


def assert_one_format(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"success", "error"}
    assert body["success"] is False
    error = body["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    # The reference number: in the body and in the header, the same value
    assert error["request_id"]
    assert error["request_id"] == response.headers["X-Request-ID"]
    for word in INTERNALS:
        assert word not in response.text, f"{word!r} leaked to the client"
    return error


@pytest.mark.parametrize(
    ("method", "path", "kwargs", "status", "code"),
    [
        ("get", "/api/v1/no-such-route", {}, 404, "not_found"),
        ("delete", "/api/v1/skills/", {}, 405, "method_not_allowed"),
        (
            "post",
            "/api/v1/auth/register",
            {"json": {"email": "not-an-email"}},
            422,
            "validation_error",
        ),
        (
            "post",
            "/api/v1/auth/register",
            {"content": b"{not json", "headers": {"Content-Type": "application/json"}},
            422,
            "validation_error",
        ),
        ("get", "/api/v1/attempts/1", {}, 401, "unauthenticated"),
        (
            "get",
            "/api/v1/attempts/1",
            {"headers": {"Authorization": "Bearer not-a-token"}},
            401,
            "unauthenticated",
        ),
        ("get", "/__test__/crash", {}, 500, "internal_error"),
        ("get", "/__test__/http-500", {}, 500, "internal_error"),
        ("get", "/__test__/app-500", {}, 500, "internal_error"),
        ("get", "/__test__/unavailable", {}, 503, "service_unavailable"),
    ],
)
async def test_every_error_has_one_format_and_a_reference(
    client, method, path, kwargs, status, code
):
    response = await getattr(client, method)(path, **kwargs)
    assert_one_format(response, status, code)


@pytest.mark.parametrize("path", ["/__test__/crash", "/__test__/http-500", "/__test__/app-500"])
async def test_a_500_never_shows_what_went_wrong(client, path):
    response = await client.get(path)
    error = assert_one_format(response, 500, "internal_error")
    assert error["message"] == "Something went wrong. Please try again later."
    assert "details" not in error


async def test_the_reference_the_client_sends_is_kept(client):
    response = await client.get("/__test__/crash", headers={"X-Request-ID": "support-ticket-42"})
    assert assert_one_format(response, 500, "internal_error")["request_id"] == "support-ticket-42"


@pytest.mark.parametrize("path", ["/__test__/crash", "/__test__/app-500"])
async def test_a_500_is_logged_with_the_reference_and_the_stack_trace(client, caplog, path):
    with caplog.at_level(logging.ERROR):
        response = await client.get(path)
    reference = response.json()["error"]["request_id"]
    records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert records, "the 500 was not logged"
    logged = " ".join(r.getMessage() + str(getattr(r, "msg", "")) for r in records)
    assert reference in logged or any(
        reference in json.dumps(r.msg, default=str) for r in records if isinstance(r.msg, dict)
    )
    # The stack trace is in the server log (never in the response)
    assert any(r.exc_info for r in records)


async def test_validation_errors_never_echo_the_submitted_values(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={"full_name": "A", "email": "nope", "phone": "1", "password": "hunter2-secret"},
    )
    error = assert_one_format(response, 422, "validation_error")
    assert "hunter2-secret" not in response.text
    assert all(set(item) <= {"loc", "msg", "type"} for item in error["details"])
