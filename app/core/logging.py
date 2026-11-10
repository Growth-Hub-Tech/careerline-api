import logging
import sys

import sentry_sdk
import structlog
from sentry_sdk.integrations.logging import LoggingIntegration

from app.core.config import settings

# Loggers from libraries that should go through the same output as our own logs.
# uvicorn.access is silenced: the request middleware writes one access line per request instead.
_LIBRARY_LOGGERS = ("uvicorn", "uvicorn.error", "sqlalchemy", "alembic", "httpx", "openai")


def configure_logging(level: str | None = None, json_logs: bool | None = None) -> None:
    level = (level or settings.LOG_LEVEL).upper()
    json_logs = settings.LOG_JSON if json_logs is None else json_logs

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,  # adds request_id bound by the middleware
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        report_errors_to_sentry,
    ]

    renderer: structlog.types.Processor
    if json_logs:
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Standard-library records (uvicorn, sqlalchemy, alembic...) are rendered by structlog too
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _LIBRARY_LOGGERS:
        library_logger = logging.getLogger(name)
        library_logger.handlers = []
        library_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)


def init_error_monitoring() -> None:
    """Send errors to Sentry when SENTRY_DSN is set (the API and the worker call this)."""
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        send_default_pii=False,
        # Request bodies hold passwords and emails, stack frames hold their values: never sent
        max_request_body_size="never",
        include_local_variables=False,
        # Error log lines are sent by report_errors_to_sentry; other lines become breadcrumbs
        integrations=[LoggingIntegration(event_level=None)],
    )


_ERROR_LEVELS = {"error", "exception", "critical"}


def report_errors_to_sentry(
    logger: object, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """One Sentry event per error log line (500s, failed and dead jobs): the exception with its
    stack trace when there is one, otherwise the event name, so events group by what went wrong
    and not by each line's request id or time."""
    if method_name in _ERROR_LEVELS and sentry_sdk.is_initialized():
        with sentry_sdk.new_scope() as scope:
            for key, value in event_dict.items():
                if key not in ("event", "exc_info", "timestamp"):
                    scope.set_extra(key, value)
            if event_dict.get("exc_info") and sys.exc_info()[1] is not None:
                sentry_sdk.capture_exception()
            else:
                sentry_sdk.capture_message(str(event_dict.get("event")), level="error")
    return event_dict
