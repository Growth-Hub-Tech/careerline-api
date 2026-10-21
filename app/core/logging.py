import logging
import sys

import structlog

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
