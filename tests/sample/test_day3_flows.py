"""Day 3 flows on sample state: a subscription checkout pending -> paid, and an invitation sent ->
accepted -> completed, end to end through the API like the frontend will do it. (Credit-pack
payments are real since Day 16: tests/integration/test_payments.py.)"""

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


async def _invite(client, auth) -> dict:
    response = await client.post(
        f"{API}/invitations",
        headers=auth,
        json={
            "email": "tobi@example.com",
            "full_name": "Tobi Adeyemi",
            "test_id": 202,
            "candidate_id": 601,
        },
    )
    return assert_sample(response, 201)


async def test_an_invitation_is_sent_accepted_and_completed(client, auth, other_auth):
    invitation = await _invite(client, auth)
    assert invitation["status"] == "sent"
    assert invitation["invite_url"].endswith(f"/invite/{invitation['token']}")
    token = invitation["token"]

    # The candidate opens the link (no login needed to see it) ...
    opened = assert_sample(await client.get(f"{API}/invitations/token/{token}"))
    assert opened["status"] == "sent" and opened["test_title"] == "Backend Development"

    # ... logs in and accepts: the test starts
    accepted = assert_sample(
        await client.post(f"{API}/invitations/token/{token}/accept", headers=other_auth)
    )
    assert accepted["status"] == "accepted" and accepted["attempt_id"]
    again = assert_sample(
        await client.post(f"{API}/invitations/token/{token}/accept", headers=other_auth)
    )
    assert again["attempt_id"] == accepted["attempt_id"]

    sender_view = f"{API}/invitations/{invitation['invitation_id']}"
    assert assert_sample(await client.get(sender_view, headers=auth))["status"] == "accepted"

    # ... and finishes the test
    completed = assert_sample(await client.post(f"{API}/sample/invitations/{token}/complete"))
    assert completed["status"] == "completed" and completed["result_id"]

    final = assert_sample(await client.get(sender_view, headers=auth))
    assert final["status"] == "completed"
    assert final["accepted_at"] and final["completed_at"] and final["result_id"]
    sent = assert_sample(await client.get(f"{API}/invitations", headers=auth))
    assert [i["status"] for i in sent["items"]] == ["completed"]


async def test_invitation_steps_cannot_happen_out_of_order(client, auth, other_auth):
    invitation = await _invite(client, auth)
    token = invitation["token"]
    # completing before accepting is out of order
    assert_sample_error(
        await client.post(f"{API}/sample/invitations/{token}/complete"), 409, "conflict"
    )
    await client.post(f"{API}/invitations/token/{token}/accept", headers=other_auth)
    await client.post(f"{API}/sample/invitations/{token}/complete")
    response = await client.post(
        f"{API}/invitations/token/{token}/revoke".replace("/token/", "/"), headers=auth
    )
    assert response.status_code in (404, 422)  # revoke is by invitation id, not token
    revoke = await client.post(
        f"{API}/invitations/{invitation['invitation_id']}/revoke", headers=auth
    )
    assert_sample_error(revoke, 409, "conflict")


async def test_an_expired_invitation_is_a_410(client, auth, other_auth):
    token = (await _invite(client, auth))["token"]
    await client.post(f"{API}/sample/invitations/{token}/expire")
    assert_sample_error(await client.get(f"{API}/invitations/token/{token}"), 410, "expired")
    accept = await client.post(f"{API}/invitations/token/{token}/accept", headers=other_auth)
    assert_sample_error(accept, 410, "expired")


async def test_a_revoked_invitation_cannot_be_accepted(client, auth, other_auth):
    invitation = await _invite(client, auth)
    revoked = await client.post(
        f"{API}/invitations/{invitation['invitation_id']}/revoke", headers=auth
    )
    assert assert_sample(revoked)["status"] == "revoked"
    accept = await client.post(
        f"{API}/invitations/token/{invitation['token']}/accept", headers=other_auth
    )
    assert_sample_error(accept, 409, "conflict")


async def test_only_the_sender_sees_an_invitation(client, auth, other_auth):
    invitation = await _invite(client, auth)
    response = await client.get(
        f"{API}/invitations/{invitation['invitation_id']}", headers=other_auth
    )
    assert_sample_error(response, 404, "not_found")


async def test_an_unknown_invitation_link_is_a_404(client):
    assert_sample_error(await client.get(f"{API}/invitations/token/inv_nope"), 404, "not_found")


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
