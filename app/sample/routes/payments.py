from typing import cast

from fastapi import APIRouter, Depends, Request

from app.core.responses import ApiResponse
from app.sample import flows
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.schemas.common import Page
from app.schemas.payments import (
    Checkout,
    CheckoutRequest,
    CreditPack,
    Credits,
    Payment,
    PaymentStatus,
    PaystackEvent,
    WebhookReceipt,
)

router = APIRouter(
    tags=["Sample: Payments"], route_class=SampleRoute, dependencies=[Depends(scenario)]
)

FLOW_NOTE = (
    "Sample flow: the checkout is pending until someone opens its authorization_url (a sample "
    "Paystack page on this API that pays it at once; add `?outcome=failed` or `?outcome=abandoned`), "
    "or POST /api/v1/payments/webhooks/paystack sends charge.success. Then this payment is paid and "
    "the credits are added."
)


def authorization_url(request: Request, reference: str) -> str:
    return str(request.url_for("sample_paystack_checkout", reference=reference))


# CREDIT PACKS: what credits cost. Public.
@router.get(
    "/payments/credit-packs",
    response_model=ApiResponse[list[CreditPack]],
    openapi_extra=sample_route(),
)
async def list_credit_packs():
    return sample(flows.CREDIT_PACKS)


# CHECKOUT: start a Paystack payment for credits or a subscription
@router.post(
    "/payments/checkout",
    status_code=201,
    response_model=ApiResponse[Checkout],
    openapi_extra=sample_route(summary_note=FLOW_NOTE),
)
async def start_checkout(
    data: CheckoutRequest, request: Request, learner_id: int = Depends(sample_user)
):
    payment = flows.create_checkout(learner_id, data.item_type, data.item_id, data.callback_url)
    return sample(
        Checkout(
            **payment.model_dump(), authorization_url=authorization_url(request, payment.reference)
        )
    )


# MY PAYMENTS: newest first
@router.get(
    "/payments", response_model=ApiResponse[Page[Payment]], openapi_extra=sample_route("empty")
)
async def list_my_payments(
    limit: int = 20,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    payments = [] if sc.empty else flows.list_payments(learner_id)
    return sample(
        Page[Payment](
            items=payments[offset : offset + limit], total=len(payments), limit=limit, offset=offset
        )
    )


# ONE PAYMENT: call this when Paystack sends the person back to callback_url?reference=...
@router.get(
    "/payments/{reference}",
    response_model=ApiResponse[Payment],
    openapi_extra=sample_route(
        "pending",
        "paid",
        "failed",
        summary_note=FLOW_NOTE + " A scenario only changes what is shown.",
    ),
)
async def get_payment(
    reference: str, sc: Scenario = Depends(scenario), learner_id: int = Depends(sample_user)
):
    payment = flows.get_payment(reference, learner_id)
    if sc.name:
        payment = payment.model_copy(update={"status": cast(PaymentStatus, sc.name)})
    return sample(payment)


# PAYSTACK WEBHOOK: Paystack calls this; the real one checks the x-paystack-signature header
@router.post(
    "/payments/webhooks/paystack",
    response_model=ApiResponse[WebhookReceipt],
    openapi_extra=sample_route(
        summary_note="Sample: `charge.success` pays the payment with that reference; other events are ignored."
    ),
)
async def paystack_webhook(event: PaystackEvent):
    if event.event == "charge.success":
        flows.settle(event.data.reference, "paid")
    return sample(WebhookReceipt(received=True))


# MY CREDITS: balance and history (credits pay for tests)
@router.get("/credits", response_model=ApiResponse[Credits], openapi_extra=sample_route())
async def get_my_credits(learner_id: int = Depends(sample_user)):
    balance, transactions = flows.credits(learner_id)
    return sample(Credits(credits_balance=balance, transactions=transactions))
