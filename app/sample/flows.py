"""The sample flows' rules, shared by the sample routes and the sample helpers.

Checkout: pending -> paid | failed | abandoned (paying twice changes nothing).
Invitation: sent -> accepted -> completed; sent or accepted can be revoked; past expires_at it is
expired.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import ConflictError, NotFoundError
from app.sample import store
from app.schemas.common import Money
from app.schemas.payments import CreditPack, CreditTransaction, ItemType, Payment
from app.schemas.subscriptions import Plan, Subscription

STARTING_CREDITS = 3

CREDIT_PACKS = [
    CreditPack(pack_id=1, name="Starter", credits=5, price=Money(amount=500_000)),
    CreditPack(pack_id=2, name="Standard", credits=12, price=Money(amount=1_000_000)),
    CreditPack(pack_id=3, name="Team", credits=60, price=Money(amount=4_500_000)),
]
PACKS_BY_ID = {pack.pack_id: pack for pack in CREDIT_PACKS}

PLANS = [
    Plan(
        plan_id=11,
        name="Individual Monthly",
        audience="individual",
        interval="monthly",
        price=Money(amount=300_000),
        credits_per_interval=5,
        seats=None,
        features=["5 test credits a month", "PDF reports", "Learning pathways"],
    ),
    Plan(
        plan_id=12,
        name="Recruiter Monthly",
        audience="recruiter",
        interval="monthly",
        price=Money(amount=2_500_000),
        credits_per_interval=40,
        seats=3,
        features=["40 candidate tests a month", "Candidate reports", "3 recruiter seats"],
    ),
    Plan(
        plan_id=13,
        name="Organisation Yearly",
        audience="organisation",
        interval="yearly",
        price=Money(amount=150_000_000),
        credits_per_interval=600,
        seats=50,
        features=["Team audits", "Capability heatmap", "Targets and progress", "50 seats"],
    ),
]
PLANS_BY_ID = {plan.plan_id: plan for plan in PLANS}


def now() -> datetime:
    return datetime.now(UTC)


# ---------- checkout ----------


def item_for(item_type: str, item_id: int) -> tuple[str, Money, int]:
    """Description, price and credits of what is being bought."""
    if item_type == "credit_pack" and item_id in PACKS_BY_ID:
        pack = PACKS_BY_ID[item_id]
        return f"{pack.credits} test credits ({pack.name})", pack.price, pack.credits
    if item_type == "subscription_plan" and item_id in PLANS_BY_ID:
        plan = PLANS_BY_ID[item_id]
        return f"{plan.name} subscription", plan.price, plan.credits_per_interval
    raise NotFoundError(f"No {item_type.replace('_', ' ')} with id {item_id}")


def create_checkout(
    learner_id: int, item_type: ItemType, item_id: int, callback_url: str | None
) -> Payment:
    description, price, credits = item_for(item_type, item_id)
    payment = Payment(
        reference=f"sample_{uuid.uuid4().hex[:16]}",
        status="pending",
        item_type=item_type,
        item_id=item_id,
        description=description,
        amount=price,
        credits_added=0,
        created_at=now(),
        paid_at=None,
    )
    with store.transaction() as state:
        state.setdefault("payments", {})[payment.reference] = {
            "payment": payment.model_dump(mode="json"),
            "learner_id": learner_id,
            "credits": credits,
            "callback_url": callback_url,
        }
    return payment


def _record(state: dict[str, Any], reference: str) -> dict[str, Any]:
    record = state.get("payments", {}).get(reference)
    if record is None:
        raise NotFoundError(f"Payment {reference} not found")
    return record


def get_payment(reference: str, learner_id: int | None = None) -> Payment:
    with store.transaction() as state:
        record = _record(state, reference)
    if learner_id is not None and record["learner_id"] != learner_id:
        raise NotFoundError(f"Payment {reference} not found")
    return Payment(**record["payment"])


def callback_url(reference: str) -> str | None:
    with store.transaction() as state:
        return _record(state, reference)["callback_url"]


def list_payments(learner_id: int) -> list[Payment]:
    with store.transaction() as state:
        records = [r for r in state.get("payments", {}).values() if r["learner_id"] == learner_id]
    payments = [Payment(**r["payment"]) for r in records]
    return sorted(payments, key=lambda p: p.created_at, reverse=True)


def settle(reference: str, outcome: str) -> Payment:
    """What Paystack's webhook does: mark the payment paid (credits added) or failed/abandoned."""
    with store.transaction() as state:
        record = _record(state, reference)
        payment = Payment(**record["payment"])
        if payment.status != "pending":
            if payment.status == "paid" and outcome == "paid":
                return payment  # Paystack can send the same event twice
            raise ConflictError(f"Payment {reference} is already {payment.status}")
        learner_id = record["learner_id"]
        if outcome == "paid":
            credits = record["credits"]
            payment = payment.model_copy(
                update={"status": "paid", "paid_at": now(), "credits_added": credits}
            )
            wallet = state.setdefault("credits", {}).setdefault(str(learner_id), [])
            balance = STARTING_CREDITS + sum(t["change"] for t in wallet)
            wallet.append(
                CreditTransaction(
                    transaction_id=next_txn_id(state),
                    change=credits,
                    reason="purchase"
                    if payment.item_type == "credit_pack"
                    else "subscription_grant",
                    balance_after=balance + credits,
                    created_at=now(),
                ).model_dump(mode="json")
            )
            if payment.item_type == "subscription_plan":
                plan = PLANS_BY_ID[payment.item_id]
                start = now()
                period = timedelta(days=365 if plan.interval == "yearly" else 30)
                state.setdefault("subscriptions", {})[str(learner_id)] = Subscription(
                    subscription_id=store.next_id(state, "subscription", 801),
                    plan_id=plan.plan_id,
                    plan_name=plan.name,
                    status="active",
                    current_period_start=start,
                    current_period_end=start + period,
                    cancel_at_period_end=False,
                    seats=plan.seats,
                ).model_dump(mode="json")
        else:
            payment = payment.model_copy(update={"status": outcome})
        record["payment"] = payment.model_dump(mode="json")
        return payment


def next_txn_id(state: dict[str, Any]) -> int:
    return store.next_id(state, "credit_transaction", 6001)


def credits(learner_id: int) -> tuple[int, list[CreditTransaction]]:
    with store.transaction() as state:
        wallet = state.get("credits", {}).get(str(learner_id), [])
    transactions = [CreditTransaction(**t) for t in wallet]
    return STARTING_CREDITS + sum(t.change for t in transactions), transactions[::-1]


def subscription(learner_id: int) -> Subscription | None:
    with store.transaction() as state:
        data = state.get("subscriptions", {}).get(str(learner_id))
    return Subscription(**data) if data else None


def cancel_subscription(learner_id: int) -> Subscription | None:
    with store.transaction() as state:
        data = state.get("subscriptions", {}).get(str(learner_id))
        if data is None:
            return None
        data["cancel_at_period_end"] = True
        return Subscription(**data)
