"""Bodies over 2 MB are refused with 413 before any route reads them."""

import httpx

from app.core.config import settings
from app.core.middleware import MAX_BODY_BYTES, BodySizeLimitMiddleware


def _echo_app():
    """Answers with the size of the body it read; counts how often it ran."""
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["path"])
        size, more = 0, True
        while more:
            message = await receive()
            size += len(message.get("body", b""))
            more = message.get("more_body", False)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": str(size).encode()})

    return app, calls


def _client(app) -> httpx.AsyncClient:
    limited = BodySizeLimitMiddleware(app, max_bytes=1000)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=limited), base_url="http://test")


def _chunks(total: int, size: int = 300):
    async def stream():
        sent = 0
        while sent < total:
            part = min(size, total - sent)
            sent += part
            yield b"x" * part

    return stream()


async def test_a_content_length_over_the_limit_is_refused_before_the_app_runs():
    app, calls = _echo_app()
    async with _client(app) as client:
        response = await client.post("/upload", content=b"x" * 1001)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert calls == []


async def test_a_body_at_the_limit_reaches_the_app_whole():
    app, calls = _echo_app()
    async with _client(app) as client:
        response = await client.post("/upload", content=b"x" * 1000)
    assert (response.status_code, response.text) == (200, "1000")
    assert calls == ["/upload"]


async def test_a_chunked_body_over_the_limit_is_refused_before_the_app_runs():
    app, calls = _echo_app()
    async with _client(app) as client:
        response = await client.post("/upload", content=_chunks(1001))
    assert response.status_code == 413
    assert calls == []


async def test_a_chunked_body_under_the_limit_reaches_the_app_whole():
    app, calls = _echo_app()
    async with _client(app) as client:
        response = await client.post("/upload", content=_chunks(900))
    assert (response.status_code, response.text) == (200, "900")


async def test_a_request_without_a_body_is_untouched():
    app, calls = _echo_app()
    async with _client(app) as client:
        response = await client.get("/page")
    assert (response.status_code, response.text) == (200, "0")


async def test_the_api_answers_a_too_large_body_with_the_error_envelope(client):
    response = await client.post(
        f"{settings.API_PREFIX}/contact",
        content=b"{" + b" " * MAX_BODY_BYTES + b"}",
        headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "payload_too_large"
    assert error["request_id"] == response.headers["X-Request-ID"]
    # inside CORS, so the website can read the answer
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
