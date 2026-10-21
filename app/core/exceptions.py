# Errors the global handler turns into the error envelope with the right status code.
# Raise these from services and routes instead of HTTPException(500, str(e)).
# Codes are lowercase snake_case, as in the API contract the frontend uses; a feature can
# subclass with its own code, e.g. code = "email_taken".
class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details=None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class GoneError(AppError):
    status_code = 410
    code = "gone"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


# Error code for each HTTP status, used when a plain HTTPException (or Starlette's 404/405) is raised
STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def code_for_status(status_code: int) -> str:
    return STATUS_CODES.get(status_code, "internal_error" if status_code >= 500 else "bad_request")
