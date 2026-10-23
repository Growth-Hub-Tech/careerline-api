# Payments go through Paystack: checkout gives an authorization_url, the person pays there,
# Paystack redirects back to callback_url and tells the API by webhook. Credits pay for tests.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Money

PaymentStatus = Literal["pending", "paid", "failed", "abandoned"]
ItemType = Literal["credit_pack", "subscription_plan"]
CreditReason = Literal["purchase", "test_started", "refund", "subscription_grant"]


class CreditPack(BaseModel):
    pack_id: int
    name: str
    credits: int
    price: Money


class CheckoutRequest(BaseModel):
    item_type: ItemType
    item_id: int
    callback_url: str | None = Field(
        default=None, description="Where Paystack sends the person after paying (?reference=...)"
    )


class Payment(BaseModel):
    reference: str
    status: PaymentStatus
    item_type: ItemType
    item_id: int
    description: str
    amount: Money
    credits_added: int
    created_at: datetime
    paid_at: datetime | None


class Checkout(Payment):
    """A new pending payment: send the person to authorization_url to pay."""

    authorization_url: str


class CreditTransaction(BaseModel):
    transaction_id: int
    change: int
    reason: CreditReason
    balance_after: int
    created_at: datetime


class Credits(BaseModel):
    credits_balance: int
    transactions: list[CreditTransaction]


class PaystackEventData(BaseModel):
    reference: str


class PaystackEvent(BaseModel):
    """The part of Paystack's webhook body the API reads (the real one also checks the signature)."""

    event: str
    data: PaystackEventData


class WebhookReceipt(BaseModel):
    received: bool
