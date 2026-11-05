"""Day 29: starting payments is rate limited per person (CHECKOUTS_PER_HOUR), so a script cannot
open thousands of Paystack transactions in someone's name."""

# ruff: noqa: F811 (pytest fixtures imported from test_payments)

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope
from tests.integration.test_payments import fake_paystack, packs  # noqa: F401

API = settings.API_PREFIX


async def test_too_many_checkouts_in_an_hour_are_refused(
    client, learner, other_learner, fake_paystack, monkeypatch
):
    monkeypatch.setattr(settings, "CHECKOUTS_PER_HOUR", 2)
    body = {"item_type": "credit_pack", "item_id": 1}
    for _ in range(2):
        response = await client.post(
            f"{API}/payments/checkout", headers=learner["headers"], json=body
        )
        assert response.status_code == 201, response.text
    refused = await client.post(f"{API}/payments/checkout", headers=learner["headers"], json=body)
    assert_error_envelope(refused, 429, "rate_limited")
    assert int(refused.headers["Retry-After"]) > 0
    assert len(fake_paystack.calls("/transaction/initialize")) == 2
    # someone else is not affected
    other = await client.post(
        f"{API}/payments/checkout", headers=other_learner["headers"], json=body
    )
    assert other.status_code == 201
