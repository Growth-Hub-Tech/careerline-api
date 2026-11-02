"""Imports every module that registers job handlers (see registry.HANDLER_MODULES)."""

from app.email import outbox  # noqa: F401
from app.services import (  # noqa: F401
    account_service,
    ai_recommendations,
    explanations,
    privacy,
    reports,
)
