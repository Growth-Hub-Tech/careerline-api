"""Job handlers by kind. A handler is `async def handler(session, payload) -> None`.

The handler's database writes commit in the same transaction that marks the job done, so they
happen exactly once. Anything outside the database (an email, an API call) can run again if a
worker dies at the wrong moment, so handlers must be idempotent: check first, then act (the
email handler skips a message already marked sent).
"""

import importlib
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]

HANDLERS: dict[str, Handler] = {}

# Modules that register handlers with @job(...); imported once by the runner
HANDLER_MODULES = ("app.jobs.handlers",)


class PermanentJobError(Exception):
    """Raise from a handler when retrying cannot help (bad payload): the job is dead-lettered."""


def job(kind: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS[kind] = handler
        return handler

    return register


def load_handlers() -> None:
    for module in HANDLER_MODULES:
        importlib.import_module(module)
