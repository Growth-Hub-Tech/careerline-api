from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Money

Audience = Literal["individual", "recruiter", "organisation"]
Interval = Literal["monthly", "yearly"]
SubscriptionStatus = Literal["active", "past_due", "cancelled"]


class Plan(BaseModel):
    plan_id: int
    name: str
    audience: Audience
    interval: Interval
    price: Money
    credits_per_interval: int
    seats: int | None
    features: list[str]


class Subscription(BaseModel):
    subscription_id: int
    plan_id: int
    plan_name: str
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    seats: int | None


class SubscribeRequest(BaseModel):
    plan_id: int
    callback_url: str | None = None
