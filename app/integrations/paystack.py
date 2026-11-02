"""Paystack (Day 16): start a transaction, check one, and check a webhook's signature.

- The secret key is settings.PAYSTACK_SECRET_KEY, from the environment only. Without it nothing
  here is called (the payment routes answer 503 first).
- Every call has a timeout. Paystack failing or not answering is PaystackError; the caller turns
  it into a 503 and nothing is charged.
- Amounts are in the smallest unit (kobo), as Paystack wants them.
- Tests never reach Paystack: they set TRANSPORT to an httpx.MockTransport.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# None = the real network; tests replace it with httpx.MockTransport
TRANSPORT: httpx.AsyncBaseTransport | None = None


class PaystackError(Exception):
    pass


@dataclass(frozen=True)
class Initialized:
    authorization_url: str
    access_code: str


@dataclass(frozen=True)
class Transaction:
    """What /transaction/verify says about a payment. status: success, failed, abandoned,
    ongoing, pending, processing, queued or reversed (Paystack's words)."""

    status: str
    amount: int
    currency: str
    transaction_id: int | None
    channel: str | None
    # a reusable card authorization (Day 25): what subscription renewals are charged to
    authorization_code: str | None = None


def configured() -> bool:
    return bool(settings.PAYSTACK_SECRET_KEY)


def new_reference() -> str:
    return f"cl_{secrets.token_hex(12)}"


def valid_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Paystack signs each webhook: x-paystack-signature is the HMAC-SHA512 of the raw body
    with the secret key, in hex."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


async def _call(method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    if not configured():
        raise PaystackError("PAYSTACK_SECRET_KEY is not set")
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    try:
        async with httpx.AsyncClient(
            base_url=settings.PAYSTACK_BASE_URL,
            timeout=settings.PAYSTACK_TIMEOUT_SECONDS,
            transport=TRANSPORT,
        ) as client:
            response = await client.request(method, path, json=json, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("paystack_unreachable", path=path, error=type(exc).__name__)
        raise PaystackError("Paystack did not answer") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or not body.get("status"):
        logger.warning(
            "paystack_refused", path=path, status=response.status_code, message=body.get("message")
        )
        raise PaystackError(f"Paystack answered {response.status_code}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise PaystackError("Paystack's answer had no data")
    return data


async def initialize(
    *,
    email: str,
    amount: int,
    currency: str,
    reference: str,
    callback_url: str,
    metadata: dict[str, Any],
) -> Initialized:
    data = await _call(
        "POST",
        "/transaction/initialize",
        json={
            "email": email,
            "amount": amount,
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata,
        },
    )
    url, code = data.get("authorization_url"), data.get("access_code")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise PaystackError("Paystack's answer had no authorization_url")
    return Initialized(authorization_url=url, access_code=str(code or ""))


async def verify(reference: str) -> Transaction:
    data = await _call("GET", f"/transaction/verify/{reference}")
    return transaction_from(data)


def transaction_from(data: dict[str, Any]) -> Transaction:
    raw_id = data.get("id")
    return Transaction(
        status=str(data.get("status") or ""),
        amount=int(data.get("amount") or 0),
        currency=str(data.get("currency") or ""),
        transaction_id=int(raw_id)
        if isinstance(raw_id, int | str) and str(raw_id).isdigit()
        else None,
        channel=data.get("channel") if isinstance(data.get("channel"), str) else None,
        authorization_code=_reusable_authorization(data.get("authorization")),
    )


def _reusable_authorization(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("reusable") is not True:
        return None
    code = value.get("authorization_code")
    return code[:64] if isinstance(code, str) and code.startswith("AUTH_") else None
