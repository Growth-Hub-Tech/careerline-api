"""Subscriptions (Days 25-26).

Plans come from seeds/subscription_plans.json. Subscribing is a Paystack checkout of item_type
subscription_plan (POST /subscriptions or POST /payments/checkout): payments.settle() calls
activate() once Paystack has the money, in the same transaction, so a plan starts exactly once
per payment. Each paid period adds the plan's credits (reason subscription_grant).

Who can buy what: an individual plan, anyone; a recruiter plan, someone with an organisation
account (owner, admin or recruiter); an organisation plan, an organisation's owner or admin, and
one per organisation. A person has one live plan at a time (active or past_due).

The period: monthly plans run to the same day next month, yearly ones to the same day next
year. Cancelling (cancel_at_period_end) keeps the plan until the period ends. A period that ends
without being paid again is past_due for SUBSCRIPTION_GRACE_DAYS, then cancelled. The status is
brought up to date whenever a subscription is read.

Seats: an organisation's seats are the most of its own seats_total (25 without a plan) and the
seats of its live organisation plan.
"""

import calendar
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.integrations import paystack
from app.models.models import Learner
from app.models.organisations import OrganisationMember
from app.models.payments import Payment
from app.models.subscriptions import Subscription, SubscriptionPlan
from app.schemas.common import Money
from app.schemas.subscriptions import Plan
from app.schemas.subscriptions import Subscription as SubscriptionOut

logger = get_logger(__name__)

LIVE = ("active", "past_due")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def add_interval(start: datetime, interval: str) -> datetime:
    """The same day next month (or year); the 31st becomes the month's last day."""
    months = 12 if interval == "yearly" else 1
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _plan_out(plan: SubscriptionPlan) -> Plan:
    return Plan(
        plan_id=plan.plan_id,
        name=plan.name,
        audience=plan.audience,
        interval=plan.interval,
        price=Money(amount=plan.price_amount, currency=plan.currency),
        credits_per_interval=plan.credits_per_interval,
        seats=plan.seats,
        features=list(plan.features or []),
    )


async def list_plans(db: AsyncSession) -> list[Plan]:
    rows = await db.scalars(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active.is_(True))
        .order_by(SubscriptionPlan.plan_id)
    )
    return [_plan_out(row) for row in rows]


def _status_now(row: Subscription, now: datetime) -> str:
    if row.status == "cancelled":
        return "cancelled"
    end = _aware(row.current_period_end)
    if now < end:
        return row.status
    if row.cancel_at_period_end:
        return "cancelled"
    if now < end + timedelta(days=settings.SUBSCRIPTION_GRACE_DAYS):
        return "past_due"
    return "cancelled"


def bring_up_to_date(row: Subscription, now: datetime | None = None) -> None:
    status = _status_now(row, now or _now())
    if status != row.status:
        logger.info("subscription_status", subscription_id=row.id, old=row.status, new=status)
        row.status = status
        row.updated_at = _now()


async def _subscription_out(db: AsyncSession, row: Subscription) -> SubscriptionOut:
    plan = await db.get(SubscriptionPlan, row.plan_id)
    return SubscriptionOut(
        subscription_id=row.id,
        plan_id=row.plan_id,
        plan_name=plan.name if plan else "",
        status=row.status,
        current_period_start=row.current_period_start,
        current_period_end=row.current_period_end,
        cancel_at_period_end=row.cancel_at_period_end,
        seats=row.seats,
    )


async def _live(db: AsyncSession, learner_id: int, lock: bool = False) -> Subscription | None:
    query = select(Subscription).where(
        Subscription.learner_id == learner_id, Subscription.status.in_(LIVE)
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is not None:
        bring_up_to_date(row)
        await db.flush()
        if row.status not in LIVE:
            return None
    return row


async def my_subscription(db: AsyncSession, learner_id: int) -> SubscriptionOut | None:
    """The live subscription, else the newest one (null: never subscribed)."""
    row = await _live(db, learner_id)
    if row is None:
        row = await db.scalar(
            select(Subscription)
            .where(Subscription.learner_id == learner_id)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(1)
        )
    return None if row is None else await _subscription_out(db, row)


async def cancel(db: AsyncSession, learner_id: int) -> SubscriptionOut:
    row = await _live(db, learner_id, lock=True)
    if row is None:
        raise NotFoundError("You have no subscription to cancel")
    if not row.cancel_at_period_end:
        row.cancel_at_period_end = True
        row.cancelled_at = _now()
        row.updated_at = _now()
        await db.flush()
        logger.info("subscription_cancelled", subscription_id=row.id)
    return await _subscription_out(db, row)


# ---------- buying ----------


async def _membership(db: AsyncSession, learner_id: int) -> OrganisationMember | None:
    return await db.scalar(
        select(OrganisationMember).where(OrganisationMember.learner_id == learner_id)
    )


async def _live_organisation_plan(db: AsyncSession, organisation_id: int) -> Subscription | None:
    for row in await db.scalars(
        select(Subscription).where(
            Subscription.organisation_id == organisation_id, Subscription.status.in_(LIVE)
        )
    ):
        bring_up_to_date(row)
        if row.status in LIVE:
            return row
    return None


async def plan_for_checkout(db: AsyncSession, learner: Learner, plan_id: int) -> SubscriptionPlan:
    """The plan this person may start paying for now (404, 403 or 409 otherwise)."""
    plan = await db.get(SubscriptionPlan, plan_id)
    if plan is None or not plan.is_active:
        raise NotFoundError(f"No subscription plan with id {plan_id}")
    if plan.audience != "individual":
        member = await _membership(db, learner.learner_id)
        if member is None:
            raise ForbiddenError(f"The {plan.name} plan is for organisation accounts")
        if plan.audience == "organisation":
            if member.role not in ("owner", "admin"):
                raise ForbiddenError(
                    f"The {plan.name} plan is bought by the organisation's owner or an admin"
                )
            other = await _live_organisation_plan(db, member.organisation_id)
            if other is not None and other.learner_id != learner.learner_id:
                raise ConflictError("Your organisation already has an organisation plan")
    live = await _live(db, learner.learner_id)
    if live is not None:
        if live.plan_id != plan.plan_id:
            raise ConflictError(
                "You already have a plan: cancel it and subscribe again once it has ended"
            )
        if live.status == "active":
            raise ConflictError("You already have this plan")
        # past_due: paying now renews it
    return plan


async def activate(db: AsyncSession, payment: Payment, transaction: paystack.Transaction) -> int:
    """A paid plan payment: start the plan, or renew the live one. Returns the credits added
    to the person by the caller (the plan's credits for the period)."""
    plan = await db.get(SubscriptionPlan, payment.item_id)
    assert plan is not None  # plans are retired, never deleted
    now = _now()
    live = await _live(db, payment.learner_id, lock=True)
    if live is not None and live.plan_id == plan.plan_id:
        start = max(now, _aware(live.current_period_end))
        if live.status == "past_due":
            start = now  # the lapsed days are not charged twice
        live.current_period_start = start
        live.current_period_end = add_interval(start, plan.interval)
        live.status = "active"
        live.updated_at = now
        row = live
        logger.info("subscription_renewed", subscription_id=row.id, reference=payment.reference)
    else:
        if live is not None:  # another plan bought meanwhile: the newer payment wins
            live.status = "cancelled"
            live.cancelled_at = now
            live.updated_at = now
            await db.flush()
        organisation_id = None
        if plan.audience == "organisation":
            member = await _membership(db, payment.learner_id)
            organisation_id = member.organisation_id if member else None
        row = Subscription(
            learner_id=payment.learner_id,
            plan_id=plan.plan_id,
            organisation_id=organisation_id,
            status="active",
            current_period_start=now,
            current_period_end=add_interval(now, plan.interval),
            cancel_at_period_end=False,
            seats=plan.seats,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        logger.info("subscription_started", plan_id=plan.plan_id, reference=payment.reference)
    if transaction.authorization_code:
        row.authorization_code = transaction.authorization_code
    await db.flush()
    payment.subscription_id = row.id
    return plan.credits_per_interval


async def organisation_seats(db: AsyncSession, organisation_id: int, own_seats: int) -> int:
    plan = await _live_organisation_plan(db, organisation_id)
    return max(own_seats, plan.seats or 0) if plan else own_seats
