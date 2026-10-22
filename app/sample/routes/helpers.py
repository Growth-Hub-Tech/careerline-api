"""Sample-only helpers: they stand in for things outside the API (Paystack's payment page, the
candidate finishing their test) so the sample flows can be clicked through end to end. They are
not part of the contract and disappear with the sample API."""

from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.core.exceptions import BadRequestError
from app.core.responses import ApiResponse
from app.sample import flows, store
from app.sample.core import SampleRoute, sample, sample_route, scenario
from app.schemas.common import Acknowledgement
from app.schemas.invitations import Invitation
from app.schemas.payments import Payment

router = APIRouter(
    prefix="/sample",
    tags=["Sample: helpers (not part of the API)"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

HELPER_NOTE = "Sample-only helper: not part of the API, never call it from production code."


# THE SAMPLE PAYSTACK PAGE: checkout's authorization_url. Opening it pays (or fails) the payment,
# then sends the browser to callback_url?reference=... like Paystack does.
@router.get(
    "/paystack/{reference}",
    name="sample_paystack_checkout",
    response_model=ApiResponse[Payment],
    responses={302: {"description": "Back to callback_url?reference=...&trxref=..."}},
    openapi_extra=sample_route(summary_note=HELPER_NOTE),
)
async def sample_paystack_checkout(
    reference: str, outcome: Literal["paid", "failed", "abandoned"] = "paid"
):
    payment = flows.settle(reference, outcome)
    callback = flows.callback_url(reference)
    if callback:
        if urlsplit(callback).scheme not in ("http", "https"):
            raise BadRequestError("callback_url must be an http(s) URL")
        separator = "&" if "?" in callback else "?"
        query = urlencode({"reference": reference, "trxref": reference})
        return RedirectResponse(f"{callback}{separator}{query}", status_code=302)
    return sample(payment)


# THE INVITEE FINISHES THE TEST (the real API does this when the attempt is submitted)
@router.post(
    "/invitations/{token}/complete",
    response_model=ApiResponse[Invitation],
    openapi_extra=sample_route(summary_note=HELPER_NOTE),
)
async def complete_invitation(token: str):
    return sample(flows.move_invitation(token, "completed"))


# MAKE AN INVITATION EXPIRE NOW (to try the 410)
@router.post(
    "/invitations/{token}/expire",
    response_model=ApiResponse[Invitation],
    openapi_extra=sample_route(summary_note=HELPER_NOTE),
)
async def expire_invitation(token: str):
    return sample(flows.expire_invitation(token))


# FORGET ALL SAMPLE PAYMENTS, SUBSCRIPTIONS, CREDITS AND INVITATIONS
@router.post(
    "/reset",
    response_model=ApiResponse[Acknowledgement],
    openapi_extra=sample_route(summary_note=HELPER_NOTE),
)
async def reset_sample_state():
    store.reset()
    return sample(Acknowledgement())
