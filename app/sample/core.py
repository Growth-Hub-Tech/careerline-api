"""What every sample route shares: the sample marker, the scenario header and the sample login.

Marker: every response from a sample route (success or error) carries X-Sample-Data: true, and
successful answers carry the message "Sample data".

Scenario header: send X-Mock-Scenario to force an edge case. The error scenarios work on every
sample route; the others (empty, pending, ...) only on the routes that list them in their
description (x-sample-scenarios in openapi.json). Anything else is a 400, so a typo never looks
like a normal answer.
"""

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.exceptions import (
    AppError,
    BadRequestError,
    ConflictError,
    ExpiredError,
    ForbiddenError,
    NotFoundError,
    PaymentRequiredError,
    RateLimitedError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.core.responses import ApiResponse, EnvelopeRoute, errors
from app.core.security import decode_access_token

SAMPLE_HEADER = "X-Sample-Data"
SCENARIO_HEADER = "X-Mock-Scenario"
SAMPLE_MESSAGE = "Sample data"
SLOW_SECONDS = 2.0


class ValidationScenarioError(AppError):
    status_code = 422
    code = "validation_error"


class InternalScenarioError(AppError):
    status_code = 500
    code = "internal_error"


def _unauthenticated() -> AppError:
    return UnauthorizedError(
        "Invalid or expired token. Please log in again.", headers={"WWW-Authenticate": "Bearer"}
    )


# Scenarios that work on every sample route: the status code and error each one forces
ERROR_SCENARIOS: dict[str, Callable[[], AppError]] = {
    "unauthenticated": _unauthenticated,
    "payment_required": lambda: PaymentRequiredError(
        "Not enough credits. Buy credits or subscribe to continue."
    ),
    "forbidden": lambda: ForbiddenError("You are not allowed to do this"),
    "not_found": lambda: NotFoundError("Not found"),
    "conflict": lambda: ConflictError("This was already done"),
    "expired": lambda: ExpiredError("This link or offer has expired"),
    "validation_error": lambda: ValidationScenarioError(
        "Request validation failed",
        details=[
            {
                "loc": ["body", "email"],
                "msg": "value is not a valid email address",
                "type": "value_error",
            }
        ],
    ),
    "rate_limited": lambda: RateLimitedError(
        "Too many requests. Try again in 30 seconds.", headers={"Retry-After": "30"}
    ),
    "server_error": lambda: InternalScenarioError("Something went wrong. Please try again later."),
    "unavailable": lambda: ServiceUnavailableError("Service unavailable. Try again shortly."),
}
# Status code of each error scenario, for the docs and the tests
ERROR_SCENARIO_STATUS = {name: make().status_code for name, make in ERROR_SCENARIOS.items()}
# Works everywhere too: waits SLOW_SECONDS, then answers normally (to test loading states)
GENERIC_SCENARIOS = (*ERROR_SCENARIOS, "slow")
# Scenarios a route can opt into with sample_route(...): each changes the success answer
ROUTE_SCENARIOS = {
    "empty": "lists come back empty",
    "pending": "the payment or job is still pending",
    "paid": "the payment has succeeded",
    "failed": "the payment or job failed",
    "generating": "the report is still being generated",
    "accepted": "the invitation was accepted",
    "completed": "the invitation's test is completed",
    "past_due": "the subscription payment is overdue",
    "cancelled": "the subscription is cancelled",
    "no_subscription": "there is no subscription",
}
ALL_SCENARIOS = (*GENERIC_SCENARIOS, *ROUTE_SCENARIOS)

# Protected sample routes need a real login token (from POST /api/v1/auth/login). The token is
# checked (signature and expiry) but no account is looked up, so recruiter and organisation routes
# can be tried with any learner token until those account types exist.
_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_PREFIX}/auth/login", auto_error=False
)


async def sample_user(token: str | None = Depends(_oauth2_scheme)) -> int:
    learner_id = decode_access_token(token) if token else None
    if learner_id is None:
        raise _unauthenticated()
    return learner_id


def sample_route(*scenarios: str, summary_note: str | None = None) -> dict[str, Any]:
    """openapi_extra for a sample route: marks it and lists the extra scenarios it supports."""
    unknown = set(scenarios) - set(ROUTE_SCENARIOS)
    if unknown:
        raise ValueError(f"Unknown sample scenarios: {sorted(unknown)}")
    extra: dict[str, Any] = {
        "x-sample": True,
        "x-sample-scenarios": [*GENERIC_SCENARIOS, *scenarios],
    }
    if summary_note:
        extra["x-sample-note"] = summary_note
    return extra


class Scenario:
    """The scenario asked for on this request (after the error scenarios were handled)."""

    def __init__(self, name: str | None):
        self.name = name

    @property
    def empty(self) -> bool:
        return self.name == "empty"


async def scenario(request: Request) -> Scenario:
    """Read X-Mock-Scenario: raise the forced error, wait for "slow", or hand the rest to the route."""
    name = (request.headers.get(SCENARIO_HEADER) or "").strip().lower() or None
    if name is None:
        return Scenario(None)
    route = request.scope.get("route")
    allowed = list(
        (getattr(route, "openapi_extra", None) or {}).get("x-sample-scenarios", GENERIC_SCENARIOS)
    )
    if name not in allowed:
        raise BadRequestError(
            f"Unknown {SCENARIO_HEADER} '{name}' for this route. Use one of: {', '.join(allowed)}"
        )
    if name in ERROR_SCENARIOS:
        raise ERROR_SCENARIOS[name]()
    if name == "slow":
        await asyncio.sleep(SLOW_SECONDS)
        return Scenario(None)
    return Scenario(name)


class SampleRoute(EnvelopeRoute):
    """EnvelopeRoute that marks the request as sample data and documents it as such."""

    def __init__(self, path: str, endpoint, **kwargs):
        extra = kwargs.get("openapi_extra") or sample_route()
        kwargs["openapi_extra"] = extra
        responses = {
            code: doc
            for code, doc in errors(400, 401, 402, 403, 404, 409, 410, 429, 500, 503).items()
        }
        responses.update(kwargs.get("responses") or {})
        kwargs["responses"] = responses
        if not kwargs.get("description"):
            kwargs["description"] = _description(extra)
        super().__init__(path, endpoint, **kwargs)

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sample_handler(request: Request):
            request.state.sample_data = True
            return await handler(request)

        return sample_handler


def _description(extra: dict[str, Any]) -> str:
    route_specific = [s for s in extra["x-sample-scenarios"] if s in ROUTE_SCENARIOS]
    lines = [
        "**Sample data** (header `X-Sample-Data: true`): a realistic, typed sample answer until this "
        "endpoint is built for real. The response shape will not change.",
    ]
    if extra.get("x-sample-note"):
        lines.append(extra["x-sample-note"])
    lines.append(
        f"Force an edge case with the `{SCENARIO_HEADER}` header: "
        + ", ".join(f"`{s}`" for s in GENERIC_SCENARIOS)
        + (
            ", and for this route "
            + ", ".join(f"`{s}` ({ROUTE_SCENARIOS[s]})" for s in route_specific)
            if route_specific
            else ""
        )
        + "."
    )
    return "\n\n".join(lines)


def sample(data: Any) -> ApiResponse[Any]:
    """Wrap a sample answer in the success envelope with the sample message."""
    return ApiResponse[Any](data=data, message=SAMPLE_MESSAGE)


class SampleDataHeaderMiddleware:
    """Adds X-Sample-Data: true to every response a sample route produced, errors included."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_marker(message: Message) -> None:
            if message["type"] == "http.response.start" and scope.get("state", {}).get(
                "sample_data"
            ):
                MutableHeaders(scope=message)[SAMPLE_HEADER] = "true"
            await send(message)

        await self.app(scope, receive, send_with_marker)
