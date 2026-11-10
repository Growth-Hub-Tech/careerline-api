"""Shapes shared by many endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.models import LevelName

__all__ = [
    "EMAIL_MAX_LENGTH",
    "FULL_NAME_MAX_LENGTH",
    "PASSWORD_MAX_LENGTH",
    "PHONE_MAX_LENGTH",
    "Acknowledgement",
    "Currency",
    "LevelName",
    "Money",
    "Page",
]

# The learner table's column sizes: a longer value is a 422, never a database error (a 500)
FULL_NAME_MAX_LENGTH = 100
EMAIL_MAX_LENGTH = 100
PHONE_MAX_LENGTH = 20
# Longer passwords are refused before hashing, so a huge one cannot tie up the server
PASSWORD_MAX_LENGTH = 128

Currency = Literal["NGN", "USD"]


class Money(BaseModel):
    # Paystack works in the smallest unit: kobo for NGN (NGN 5,000.00 = 500000), cents for USD
    amount: int = Field(description="Amount in the smallest unit (kobo for NGN, cents for USD)")
    currency: Currency = "NGN"


class Page[T](BaseModel):
    """One page of a list: send limit and offset as query parameters."""

    items: list[T]
    total: int
    limit: int
    offset: int


class Acknowledgement(BaseModel):
    """For actions with nothing else to return (e.g. a password reset email was queued)."""

    status: Literal["accepted"] = "accepted"
