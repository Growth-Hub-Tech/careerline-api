import functools
import inspect
from typing import Any, Literal

from fastapi.datastructures import Default, DefaultPlaceholder
from fastapi.dependencies.utils import get_flat_params
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response


# SUCCESS ENVELOPE: every API route's data is returned as {"success": true, "message": ..., "data": ...}
class ApiResponse[T](BaseModel):
    success: Literal[True] = True
    message: str | None = None
    data: T | None = None


# ERROR ENVELOPE: every error is returned as {"success": false, "error": {...}}
class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any | None = None


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail


# Return this from a route to add a message to the envelope; plain data is wrapped automatically
def ok(data: Any = None, message: str | None = None) -> ApiResponse[Any]:
    return ApiResponse[Any](data=data, message=message)


# Wraps whatever a route returns in ApiResponse and documents ApiResponse[...] in OpenAPI.
# Set it as route_class on every APIRouter that serves API routes (it is FastAPI's version of an interceptor).
class EnvelopeRoute(APIRoute):
    def __init__(
        self, path: str, endpoint, *, response_model: Any = Default(None), responses=None, **kwargs
    ):
        if not getattr(endpoint, "__enveloped__", False):
            endpoint = _enveloped(endpoint)

        # include_router builds each route again from the first one, so only wrap once
        if isinstance(response_model, DefaultPlaceholder) or response_model is None:
            response_model = ApiResponse[Any]
        elif not (inspect.isclass(response_model) and issubclass(response_model, ApiResponse)):
            response_model = ApiResponse[response_model]

        # Validation errors use the error envelope, not FastAPI's default body
        responses = {422: _error_doc(422), **(responses or {})}
        super().__init__(
            path, endpoint, response_model=response_model, responses=responses, **kwargs
        )

        # A route without parameters or body can never return 422, so don't document one
        if not get_flat_params(self.dependant) and self.body_field is None:
            self.responses.pop(422, None)
            self.response_fields.pop(422, None)


def _enveloped(endpoint):
    @functools.wraps(endpoint)
    async def wrapper(*args, **kwargs):
        if inspect.iscoroutinefunction(endpoint):
            result = await endpoint(*args, **kwargs)
        else:
            result = await run_in_threadpool(endpoint, *args, **kwargs)
        if isinstance(result, (Response, ApiResponse)):
            return result
        return ApiResponse[Any](data=result)

    wrapper.__enveloped__ = True  # type: ignore[attr-defined]
    return wrapper


# Error responses shown in Swagger (/docs).
# FastAPI only lists 200 and 422 by itself, so the other codes showed as "Undocumented".
ERRORS = {
    400: "Bad request: invalid input (the message says what is wrong)",
    401: "Not logged in: missing, invalid or expired token",
    403: "Not allowed: this belongs to another learner",
    404: "Not found",
    409: "Conflict: this attempt was already submitted",
    410: "Gone: this old route is retired (see the message for the new one)",
    422: "Validation error: the request body or parameters are invalid (see details)",
}


def _error_doc(code: int) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": ERRORS[code]}


# Pick the codes a route can return, e.g. responses=errors(401, 403, 404)
def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _error_doc(code) for code in codes}
