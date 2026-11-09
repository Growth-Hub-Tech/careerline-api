from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.payments import Checkout, CheckoutRequest
from app.schemas.subscriptions import Plan, SubscribeRequest, Subscription
from app.services import payments as payment_service
from app.services import subscriptions as subscription_service

# SUBSCRIPTIONS (Day 25, real since then): plans, subscribing through a Paystack checkout, my
# subscription, cancelling at the end of the period
router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"], route_class=EnvelopeRoute)


# PLANS: individual, recruiter and organisation plans. Public.
@router.get("/plans", response_model=list[Plan])
async def list_plans(db: AsyncSession = Depends(get_db, scope="function")):
    return await subscription_service.list_plans(db)


# MY SUBSCRIPTION: data is null when there has never been one
@router.get(
    "/me",
    response_model=Subscription | None,
    responses=errors(401),
    description="The live subscription (status active, or past_due: its period ended unpaid and "
    "it is still usable for the grace days), else the newest ended one (status cancelled), else "
    "null.",
)
async def get_my_subscription(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await subscription_service.my_subscription(db, current_learner.learner_id)


# SUBSCRIBE: a Paystack checkout for a plan (the same as POST /payments/checkout)
@router.post(
    "",
    status_code=201,
    response_model=Checkout,
    responses=errors(400, 401, 403, 404, 409, 503),
    description="The same as POST /payments/checkout with item_type subscription_plan: send the "
    "person to authorization_url, then GET /payments/{reference}. Once paid the plan is active "
    "for its period (a month or a year) and its credits are added. 403: a recruiter plan needs "
    "an organisation account, an organisation plan its owner or an admin. 409: a plan is "
    "already live (cancel it first) or the organisation already has one. A past_due plan can be "
    "paid again here.",
)
async def subscribe(
    data: SubscribeRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    request = CheckoutRequest(
        item_type="subscription_plan", item_id=data.plan_id, callback_url=data.callback_url
    )
    return await payment_service.start_checkout(db, current_learner, request)


# RESUME (Day 31): undo a cancellation while the paid period still runs
@router.post(
    "/me/resume",
    response_model=Subscription,
    responses=errors(401, 409),
    description="Undoes cancel_at_period_end while the period is still running. 409: the plan is "
    "not cancelled, or there is no live plan to resume.",
)
async def resume_my_subscription(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await subscription_service.resume(db, current_learner.learner_id)


# CANCEL: the plan stays until the end of the period
@router.post(
    "/me/cancel",
    response_model=Subscription,
    responses=errors(401, 404),
    description="Sets cancel_at_period_end: the plan (and its seats) stays until "
    "current_period_end and is not renewed. Calling it again changes nothing. 404: no live plan.",
)
async def cancel_my_subscription(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await subscription_service.cancel(db, current_learner.learner_id)
