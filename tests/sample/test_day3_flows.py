"""Day 3 flows on sample state: a subscription checkout pending -> paid, end to end through the API
like the frontend will do it. (Credit-pack payments are real since Day 16:
tests/integration/test_payments.py; invitations since Day 19: tests/integration/
test_recruiter.py and test_invitation_links.py.)"""

import os
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from app.core.config import settings
from tests.sample.conftest import API, assert_sample, assert_sample_error


def _path(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


async def _subscribe(client, auth, **body) -> dict:
    response = await client.post(f"{API}/subscriptions", headers=auth, json={"plan_id": 11, **body})
    return assert_sample(response, 201)


# Payments and credits are real since Day 16 (tests/integration/test_payments.py). Until
# subscriptions are real, their checkout is paid on the sample Paystack page.


async def test_subscribing_is_a_checkout_and_the_plan_is_active_once_paid(client, auth):
    assert assert_sample(await client.get(f"{API}/subscriptions/me", headers=auth)) is None

    checkout = await _subscribe(client, auth, callback_url="https://app.example.com/paid")
    assert checkout["status"] == "pending" and checkout["item_type"] == "subscription_plan"
    # The person pays on the (sample) Paystack page and is sent back to callback_url
    paystack = await client.get(_path(checkout["authorization_url"]))
    assert paystack.status_code == 302
    back = urlsplit(paystack.headers["location"])
    assert back.netloc == "app.example.com" and back.path == "/paid"
    assert parse_qs(back.query)["reference"] == [checkout["reference"]]

    subscription = assert_sample(await client.get(f"{API}/subscriptions/me", headers=auth))
    assert subscription["status"] == "active" and subscription["plan_id"] == 11
    cancelled = assert_sample(await client.post(f"{API}/subscriptions/me/cancel", headers=auth))
    assert cancelled["cancel_at_period_end"] is True and cancelled["status"] == "active"


async def test_a_failed_sample_payment_cannot_be_paid_later(client, auth):
    checkout = await _subscribe(client, auth)
    failed = assert_sample(
        await client.get(_path(checkout["authorization_url"]) + "?outcome=failed")
    )
    assert failed["status"] == "failed"
    response = await client.get(_path(checkout["authorization_url"]))
    assert_sample_error(response, 409, "conflict")
    assert assert_sample(await client.get(f"{API}/subscriptions/me", headers=auth)) is None


async def test_subscription_scenarios(client, auth):
    for state in ("past_due", "cancelled"):
        response = await client.get(
            f"{API}/subscriptions/me", headers={**auth, "X-Mock-Scenario": state}
        )
        assert assert_sample(response)["status"] == state
    none = await client.get(
        f"{API}/subscriptions/me", headers={**auth, "X-Mock-Scenario": "no_subscription"}
    )
    assert assert_sample(none) is None


async def test_cancelling_without_a_subscription_is_a_404(client, auth):
    assert_sample_error(
        await client.post(f"{API}/subscriptions/me/cancel", headers=auth), 404, "not_found"
    )


async def test_sample_state_is_shared_between_server_workers(client, auth):
    """Render runs several workers: each is a separate process, so state lives in a file."""
    checkout = await _subscribe(client, auth)
    code = (
        f"from app.sample import flows; print(flows.get_payment('{checkout['reference']}').status)"
    )
    env = {**os.environ, "SAMPLE_STATE_FILE": settings.SAMPLE_STATE_FILE}
    other_worker = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert other_worker.stdout.strip() == "pending"


async def test_reset_forgets_every_sample_flow(client, auth):
    checkout = await _subscribe(client, auth)
    assert assert_sample(await client.post(f"{API}/sample/reset")) == {"status": "accepted"}
    response = await client.get(_path(checkout["authorization_url"]))
    assert_sample_error(response, 404, "not_found")
