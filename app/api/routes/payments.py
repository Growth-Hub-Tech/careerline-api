from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.common import Page
from app.schemas.payments import (
    Checkout,
    CheckoutRequest,
    CreditPack,
    Credits,
    Payment,
    WebhookReceipt,
)
from app.services import payments as payment_service

# PAYMENTS (Day 16, real since then): Paystack checkout for credit packs, the signed webhook,
# my payments and my credits
router = APIRouter(tags=["Payments"], route_class=EnvelopeRoute)


# CREDIT PACKS: what credits cost. Public.
@router.get("/payments/credit-packs", response_model=list[CreditPack])
async def list_credit_packs(db: AsyncSession = Depends(get_db, scope="function")):
    return await payment_service.list_credit_packs(db)


# CHECKOUT: start a Paystack payment for a credit pack
@router.post(
    "/payments/checkout",
    status_code=201,
    response_model=Checkout,
    responses=errors(400, 401, 404, 503),
    description="Saves a pending payment and starts a Paystack transaction: send the person to "
    "authorization_url. Paystack sends them back to callback_url?reference=... (default: the "
    "website's /payments/callback; it must be a page of the website, 400 otherwise); then call "
    "GET /payments/{reference}. Only item_type credit_pack is on sale (400 for "
    "subscription_plan). 503 when payments are not set up or Paystack does not answer: nothing "
    "is charged.",
)
async def start_checkout(
    data: CheckoutRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await payment_service.start_checkout(db, current_learner, data)


# MY PAYMENTS: newest first
@router.get("/payments", response_model=Page[Payment], responses=errors(401))
async def list_my_payments(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await payment_service.list_payments(db, current_learner.learner_id, limit, offset)


# ONE PAYMENT: call this when Paystack sends the person back to callback_url?reference=...
@router.get(
    "/payments/{reference}",
    response_model=Payment,
    responses=errors(401, 404),
    description="A pending payment is checked with Paystack first, so this shows paid as soon "
    "as Paystack has the money (even before its webhook arrives). Someone else's payment is 404.",
)
async def get_payment(
    reference: str,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await payment_service.get_payment(db, reference, current_learner.learner_id)


# PAYSTACK WEBHOOK: Paystack calls this; the x-paystack-signature header is checked
@router.post(
    "/payments/webhooks/paystack",
    response_model=WebhookReceipt,
    responses=errors(400, 401, 503),
    description="For Paystack only. The body must carry a valid x-paystack-signature (HMAC-SHA512 "
    "of the raw body with the secret key), 401 otherwise. charge.success pays the payment with "
    "that reference once; every event is stored once, so retries change nothing.",
)
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db, scope="function")):
    body = await request.body()
    await payment_service.handle_webhook(db, body, request.headers.get("x-paystack-signature"))
    return WebhookReceipt(received=True)


# MY CREDITS: balance and the latest 50 changes (credits pay for tests)
@router.get("/credits", response_model=Credits, responses=errors(401))
async def get_my_credits(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await payment_service.my_credits(db, current_learner.learner_id)
