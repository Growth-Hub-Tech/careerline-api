from fastapi import APIRouter, Depends, Request

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample import flows
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.routes.payments import authorization_url
from app.schemas.payments import Checkout
from app.schemas.subscriptions import Plan, SubscribeRequest, Subscription

router = APIRouter(
    prefix="/subscriptions",
    tags=["Sample: Subscriptions"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)


# PLANS: individual, recruiter and organisation plans. Public.
@router.get("/plans", response_model=ApiResponse[list[Plan]], openapi_extra=sample_route())
async def list_plans():
    return sample(flows.PLANS)


# MY SUBSCRIPTION: data is null when there is none
@router.get(
    "/me",
    response_model=ApiResponse[Subscription | None],
    openapi_extra=sample_route(
        "past_due",
        "cancelled",
        "no_subscription",
        summary_note="Without a scenario: the subscription bought through the sample checkout, or null.",
    ),
)
async def get_my_subscription(
    sc: Scenario = Depends(scenario), learner_id: int = Depends(sample_user)
):
    if sc.name == "no_subscription":
        return sample(None)
    current = flows.subscription(learner_id)
    if sc.name in ("past_due", "cancelled"):
        plan = flows.PLANS[0]
        base = current or Subscription(
            subscription_id=800,
            plan_id=plan.plan_id,
            plan_name=plan.name,
            status="active",
            current_period_start=flows.now(),
            current_period_end=flows.now(),
            cancel_at_period_end=False,
            seats=None,
        )
        current = base.model_copy(update={"status": sc.name})
    return sample(current)


# SUBSCRIBE: starts a checkout for the plan (pay it like any checkout); active once paid
@router.post(
    "", status_code=201, response_model=ApiResponse[Checkout], openapi_extra=sample_route()
)
async def subscribe(
    data: SubscribeRequest, request: Request, learner_id: int = Depends(sample_user)
):
    payment = flows.create_checkout(
        learner_id, "subscription_plan", data.plan_id, data.callback_url
    )
    return sample(
        Checkout(
            **payment.model_dump(), authorization_url=authorization_url(request, payment.reference)
        )
    )


# CANCEL: stays active until the end of the period that was paid for
@router.post("/me/cancel", response_model=ApiResponse[Subscription], openapi_extra=sample_route())
async def cancel_my_subscription(learner_id: int = Depends(sample_user)):
    cancelled = flows.cancel_subscription(learner_id)
    if cancelled is None:
        raise NotFoundError("You have no subscription")
    return sample(cancelled)
