"""Shapes shared by many endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.models import LevelName

__all__ = ["Acknowledgement", "Currency", "LevelName", "Money", "Page"]

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
