import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError, code_for_status
from app.core.logging import get_logger
from app.core.responses import ErrorDetail, ErrorResponse

logger = get_logger(__name__)

INTERNAL_ERROR_MESSAGE = "Something went wrong. Please try again later."


# Builds the error envelope. Used by every handler below and by the request middleware for 500s.
def error_response(
    request_id: str | None,
    status_code: int,
    code: str,
    message: str,
    details=None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # Every error has a reference number. The request middleware always sets one; this fallback
    # only matters if an error is ever rendered outside it.
    request_id = request_id or uuid.uuid4().hex
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id, details=details)
    )
    response_headers = dict(headers or {})
    response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(body, exclude_none=True),
        headers=response_headers,
    )


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    message, details = exc.message, exc.details
    if exc.status_code >= 500:
        # Logged once, with the stack trace and the request id (bound by the middleware).
        # Handlers run inside Starlette's `except` block, so .exception() has the traceback.
        logger.exception("app_error", code=exc.code, status=exc.status_code, message=exc.message)
    if exc.status_code == 500:
        # A 500 is always our fault: its text is for the logs, never for the client.
        # (503 and the other 5xx keep their message: they are written for users, e.g. "try again".)
        message, details = INTERNAL_ERROR_MESSAGE, None
    return error_response(
        _request_id(request), exc.status_code, exc.code, message, details, exc.headers
    )


# HTTPException raised by routes and dependencies, and Starlette's own 404 / 405
async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status_code = exc.status_code
    if isinstance(exc.detail, str):
        message, details = exc.detail, None
    else:
        message, details = "Request failed", exc.detail
    if status_code >= 500:
        # Never send internals to the client
        logger.exception("http_error", status=status_code, detail=exc.detail)
        message, details = INTERNAL_ERROR_MESSAGE, None
    return error_response(
        _request_id(request),
        status_code,
        code_for_status(status_code),
        message,
        details,
        dict(exc.headers) if exc.headers else None,
    )


# Body / query / path validation. The submitted value ("input") is dropped so passwords never come back.
async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"loc": list(error.get("loc", ())), "msg": error.get("msg"), "type": error.get("type")}
        for error in exc.errors()
    ]
    return error_response(
        _request_id(request), 422, "validation_error", "Request validation failed", details
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Unhandled exceptions are caught by RequestContextMiddleware (app/core/middleware.py),
    # which logs them once with the request id and returns a generic 500.
