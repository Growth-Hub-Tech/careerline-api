import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.error_handlers import INTERNAL_ERROR_MESSAGE, error_response
from app.core.logging import get_logger

logger = get_logger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
# No route needs more: the biggest real body, a 1,000-person staff list, is about 300 KB
MAX_BODY_BYTES = 2 * 1024 * 1024
# An inbound request id is reused only if it is short and plain, so it can't inject anything into logs
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


# Gives every request an id (reused from X-Request-ID when valid), binds it to every log line,
# returns it in the X-Request-ID header, writes one access log line, and turns any unhandled
# exception into the generic 500 error envelope.
class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = _header(scope, b"x-request-id")
        request_id = inbound if inbound and _VALID_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        status_code = 500
        response_started = False
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                logger.exception("unhandled_error", method=scope["method"], path=scope["path"])
                if response_started:
                    raise
                response = error_response(request_id, 500, "internal_error", INTERNAL_ERROR_MESSAGE)
                await response(scope, receive, send_with_request_id)
            finally:
                # Path only: query strings can carry tokens or emails
                logger.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status_code,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
                )


# Standard security headers on every response (HSTS only in production, where HTTPS is guaranteed)
class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Answers 413 for a body over max_bytes before the route reads any of it. With a Content-Length
# the header decides (the server never passes on more than it says). Without one (a chunked
# body) the body is read here first, up to the limit, and then handed to the app.
class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        length = _header(scope, b"content-length")
        if length is not None:
            if length.isdigit() and int(length) > self.max_bytes:
                await self._too_large(scope, receive, send)
            else:
                await self.app(scope, receive, send)
            return

        received: list[Message] = []
        size = 0
        while True:
            message = await receive()
            received.append(message)
            if message["type"] != "http.request":
                break  # the client went away: the app sees that too
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                await self._too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            return received.pop(0) if received else await receive()

        await self.app(scope, replay, send)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        megabytes = self.max_bytes // (1024 * 1024)
        response = error_response(
            request_id,
            413,
            "payload_too_large",
            f"The request is too large: send at most {megabytes} MB.",
        )
        await response(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None
