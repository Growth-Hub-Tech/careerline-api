"""Payments and credits (Day 16, Paystack).

The flow: POST /payments/checkout saves a pending payment and starts a Paystack transaction; the
person pays on Paystack's page and comes back to callback_url?reference=...; Paystack tells the
API by webhook (charge.success). GET /payments/{reference} also asks Paystack about a pending
payment, so a late webhook never leaves the person waiting.

Paying exactly once: every way of settling (webhook, verify) goes through settle(), which locks
the payment row, does nothing unless it is still pending, checks Paystack's amount and currency
against ours, then marks it paid and adds the credits in the same transaction. The credit
transaction is unique per payment, and each webhook event is stored once, so retries and races
change nothing.

No real money in tests or on the test server: the key is a Paystack test key there.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    NotFoundError,
    PaymentRequiredError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.core.logging import get_logger
from app.integrations import paystack
from app.models.models import Learner
from app.models.payments import (
    CreditBalance,
    CreditPack,
    CreditTransaction,
    Payment,
    PaystackEvent,
    TestPrice,
)
from app.schemas.common import Money, Page
from app.schemas.payments import Checkout, CheckoutRequest, Credits
from app.schemas.payments import CreditPack as CreditPackOut
from app.schemas.payments import CreditTransaction as CreditTransactionOut
from app.schemas.payments import Payment as PaymentOut

logger = get_logger(__name__)

UNAVAILABLE = "Payments are not available right now. Please try again later."
CALLBACK_PATH = "/payments/callback"
HISTORY_LIMIT = 50
# Paystack's statuses that mean the money will not come
FAILED_STATUSES = {"failed", "reversed"}


def _require_paystack() -> None:
    if not paystack.configured():
        raise ServiceUnavailableError(UNAVAILABLE)


# ---------- credit packs ----------


def _pack_out(pack: CreditPack) -> CreditPackOut:
    return CreditPackOut(
        pack_id=pack.pack_id,
        name=pack.name,
        credits=pack.credits,
        price=Money(amount=pack.price_amount, currency=pack.currency),
    )


async def list_credit_packs(db: AsyncSession) -> list[CreditPackOut]:
    packs = await db.scalars(
        select(CreditPack).where(CreditPack.is_active.is_(True)).order_by(CreditPack.pack_id)
    )
    return [_pack_out(p) for p in packs]


# ---------- checkout ----------


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def callback_url_for(requested: str | None) -> str:
    """Where Paystack sends the person back: the website only (FRONTEND_URL or a CORS origin),
    so a checkout can never be used to send someone to another site."""
    if not requested:
        return settings.FRONTEND_URL.rstrip("/") + CALLBACK_PATH
    parts = urlsplit(requested)
    allowed = {_origin(settings.FRONTEND_URL), *(_origin(o) for o in settings.CORS_ORIGINS)}
    if parts.scheme not in ("http", "https") or _origin(requested) not in allowed:
        raise BadRequestError("callback_url must be a page of the CareerLine website")
    return requested


def _payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut(
        reference=payment.reference,
        status=payment.status,
        item_type=payment.item_type,
        item_id=payment.item_id,
        description=payment.description,
        amount=Money(amount=payment.amount, currency=payment.currency),
        credits_added=payment.credits if payment.status == "paid" else 0,
        created_at=payment.created_at,
        paid_at=payment.paid_at,
    )


async def start_checkout(db: AsyncSession, learner: Learner, data: CheckoutRequest) -> Checkout:
    """A credit pack (Day 16) or a subscription plan (Day 25)."""
    if data.item_type == "subscription_plan":
        from app.services import subscriptions  # subscriptions uses this module

        plan = await subscriptions.plan_for_checkout(db, learner, data.item_id)
        item_id, description = plan.plan_id, f"{plan.name} subscription"
        amount, currency, credits = plan.price_amount, plan.currency, plan.credits_per_interval
    else:
        pack = await db.get(CreditPack, data.item_id)
        if pack is None or not pack.is_active:
            raise NotFoundError(f"No credit pack with id {data.item_id}")
        item_id, description = pack.pack_id, f"{pack.credits} test credits ({pack.name})"
        amount, currency, credits = pack.price_amount, pack.currency, pack.credits
    callback = callback_url_for(data.callback_url)
    _require_paystack()

    reference = paystack.new_reference()
    try:
        started = await paystack.initialize(
            email=learner.email,
            amount=amount,
            currency=currency,
            reference=reference,
            callback_url=callback,
            metadata={
                "learner_id": learner.learner_id,
                "item_type": data.item_type,
                "item_id": item_id,
            },
        )
    except paystack.PaystackError as exc:
        raise ServiceUnavailableError(UNAVAILABLE) from exc

    payment = Payment(
        reference=reference,
        learner_id=learner.learner_id,
        item_type=data.item_type,
        item_id=item_id,
        description=description,
        amount=amount,
        currency=currency,
        credits=credits,
        status="pending",
        authorization_url=started.authorization_url,
        access_code=started.access_code,
        callback_url=callback,
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)
    logger.info(
        "checkout_started",
        reference=reference,
        learner_id=learner.learner_id,
        item_type=data.item_type,
    )
    return Checkout(
        **_payment_out(payment).model_dump(), authorization_url=started.authorization_url
    )


# ---------- settling ----------


async def _locked_balance(db: AsyncSession, learner_id: int) -> CreditBalance:
    await db.execute(
        insert(CreditBalance)
        .values(learner_id=learner_id, balance=0)
        .on_conflict_do_nothing(index_elements=[CreditBalance.learner_id])
    )
    balance = await db.scalar(
        select(CreditBalance).where(CreditBalance.learner_id == learner_id).with_for_update()
    )
    assert balance is not None
    return balance


async def _add_credits(
    db: AsyncSession,
    learner_id: int,
    change: int,
    reason: str,
    payment_id: int | None = None,
    attempt_id: int | None = None,
) -> CreditTransaction:
    balance = await _locked_balance(db, learner_id)
    balance.balance += change
    entry = CreditTransaction(
        learner_id=learner_id,
        change=change,
        reason=reason,
        balance_after=balance.balance,
        payment_id=payment_id,
        attempt_id=attempt_id,
    )
    db.add(entry)
    await db.flush()
    return entry


# ---------- credits pay for tests (Day 17) ----------


async def test_price(db: AsyncSession, skill_id: int) -> int:
    price = await db.scalar(select(TestPrice.price_credits).where(TestPrice.skill_id == skill_id))
    return price or 0


async def charge_for_test(db: AsyncSession, learner_id: int, attempt_id: int, price: int) -> None:
    """Take a new test's credits (402 when there are not enough). Runs in the transaction that
    creates the attempt, so a 402 leaves no attempt behind."""
    if price <= 0:
        return
    balance = await _locked_balance(db, learner_id)
    if balance.balance < price:
        raise PaymentRequiredError(
            f"This test costs {price} credits and you have {balance.balance}: buy a credit pack"
        )
    await _add_credits(db, learner_id, -price, "test_started", attempt_id=attempt_id)


async def refund_test(db: AsyncSession, learner_id: int, attempt_id: int) -> bool:
    """Give back what a test cost, once (a test that ended before any answer). False when it
    cost nothing or was already given back."""
    charged = await db.scalar(
        select(CreditTransaction).where(
            CreditTransaction.attempt_id == attempt_id,
            CreditTransaction.reason == "test_started",
        )
    )
    if charged is None:
        return False
    await _locked_balance(db, learner_id)  # one change at a time
    refunded = await db.scalar(
        select(CreditTransaction.id).where(
            CreditTransaction.attempt_id == attempt_id, CreditTransaction.reason == "refund"
        )
    )
    if refunded is not None:
        return False
    await _add_credits(db, learner_id, -charged.change, "refund", attempt_id=attempt_id)
    logger.info("test_refunded", attempt_id=attempt_id, credits=-charged.change)
    return True


async def settle(
    db: AsyncSession, reference: str, transaction: paystack.Transaction, source: str
) -> Payment | None:
    """Apply what Paystack says about a payment, once. Returns the payment (None if unknown)."""
    payment = await db.scalar(
        select(Payment).where(Payment.reference == reference).with_for_update()
    )
    if payment is None:
        logger.warning("paystack_unknown_reference", reference=reference, source=source)
        return None
    if payment.status != "pending":
        return payment  # already settled: a retry or a race, nothing to do
    if transaction.status == "success":
        if transaction.amount != payment.amount or transaction.currency != payment.currency:
            logger.error(
                "paystack_amount_mismatch",
                reference=reference,
                expected=payment.amount,
                got=transaction.amount,
                currency=transaction.currency,
                source=source,
            )
            return payment  # never pay on a wrong amount; stays pending for a person to look at
        payment.status = "paid"
        payment.paid_at = datetime.now(UTC)
        payment.paystack_transaction_id = transaction.transaction_id
        payment.channel = transaction.channel
        if payment.item_type == "subscription_plan":
            from app.services import subscriptions  # subscriptions uses this module

            payment.credits = await subscriptions.activate(db, payment, transaction)
            await _add_credits(
                db, payment.learner_id, payment.credits, "subscription_grant", payment.id
            )
        else:
            await _add_credits(db, payment.learner_id, payment.credits, "purchase", payment.id)
        logger.info("payment_paid", reference=reference, source=source)
    elif transaction.status in FAILED_STATUSES:
        payment.status = "failed"
        logger.info("payment_failed", reference=reference, source=source)
    elif transaction.status == "abandoned" and _old(payment):
        payment.status = "abandoned"
    await db.flush()
    return payment


def _old(payment: Payment) -> bool:
    created = payment.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return datetime.now(UTC) - created > timedelta(minutes=settings.PAYMENT_ABANDON_MINUTES)


# ---------- reading ----------


async def _own_payment(db: AsyncSession, reference: str, learner_id: int) -> Payment:
    payment = await db.scalar(select(Payment).where(Payment.reference == reference))
    if payment is None or payment.learner_id != learner_id:
        raise NotFoundError(f"Payment {reference} not found")
    return payment


async def get_payment(db: AsyncSession, reference: str, learner_id: int) -> PaymentOut:
    payment = await _own_payment(db, reference, learner_id)
    if payment.status == "pending" and paystack.configured():
        try:
            transaction = await paystack.verify(reference)
        except paystack.PaystackError:
            transaction = None  # Paystack is down: show it as it is; the webhook will come
        if transaction is not None:
            settled = await settle(db, reference, transaction, source="verify")
            if settled is not None:
                payment = settled
    return _payment_out(payment)


async def list_payments(
    db: AsyncSession, learner_id: int, limit: int, offset: int
) -> Page[PaymentOut]:
    mine = select(Payment).where(Payment.learner_id == learner_id)
    total = await db.scalar(select(func.count()).select_from(mine.subquery())) or 0
    payments = await db.scalars(
        mine.order_by(Payment.created_at.desc(), Payment.id.desc()).limit(limit).offset(offset)
    )
    return Page[PaymentOut](
        items=[_payment_out(p) for p in payments], total=total, limit=limit, offset=offset
    )


async def credit_balance(db: AsyncSession, learner_id: int) -> int:
    balance = await db.scalar(
        select(CreditBalance.balance).where(CreditBalance.learner_id == learner_id)
    )
    return balance or 0


async def my_credits(db: AsyncSession, learner_id: int) -> Credits:
    entries = await db.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.learner_id == learner_id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return Credits(
        credits_balance=await credit_balance(db, learner_id),
        transactions=[
            CreditTransactionOut(
                transaction_id=e.id,
                change=e.change,
                reason=e.reason,
                balance_after=e.balance_after,
                created_at=e.created_at,
            )
            for e in entries
        ],
    )


# ---------- the webhook ----------


async def handle_webhook(db: AsyncSession, body: bytes, signature: str | None) -> None:
    _require_paystack()
    if not paystack.valid_signature(body, signature, settings.PAYSTACK_SECRET_KEY):
        logger.warning("paystack_bad_signature")
        raise UnauthorizedError("Invalid Paystack signature")
    try:
        event: dict[str, Any] = json.loads(body)
    except ValueError as exc:
        raise BadRequestError("The webhook body is not JSON") from exc
    name = str(event.get("event") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    assert isinstance(data, dict)
    reference = data.get("reference") if isinstance(data.get("reference"), str) else None
    paystack_id = str(data.get("id") or hashlib.sha256(body).hexdigest())

    stored = await db.execute(
        insert(PaystackEvent)
        .values(
            event=name[:80],
            paystack_id=paystack_id[:128],
            reference=reference[:64] if reference else None,
            payload=event,
            outcome="received",
        )
        .on_conflict_do_nothing(constraint="uq_paystack_events_event")
        .returning(PaystackEvent.id)
    )
    event_row = stored.scalar()
    if event_row is None:
        logger.info("paystack_event_repeated", paystack_event=name, reference=reference)
        return  # seen before: Paystack retried

    outcome = "ignored"
    if name == "charge.success" and reference:
        payment = await settle(db, reference, paystack.transaction_from(data), source="webhook")
        outcome = "unknown_reference" if payment is None else f"payment_{payment.status}"
    row = await db.get(PaystackEvent, event_row)
    if row is not None:
        row.outcome = outcome
    logger.info("paystack_event", paystack_event=name, reference=reference, outcome=outcome)
