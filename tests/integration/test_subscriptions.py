"""Day 25: subscriptions part 1: plans, subscribing through Paystack, cancelling.

Plans are real (seeds/subscription_plans.json): individual, recruiter and organisation. Subscribing
is a Paystack checkout (POST /subscriptions, or POST /payments/checkout with item_type
subscription_plan); once Paystack has the money the plan is active for its period and its
credits are added (reason subscription_grant). An organisation plan is bought by an owner or an
admin and gives the organisation its seats. Cancelling keeps the plan until the period ends.
"""

# ruff: noqa: F811 (pytest fixtures imported from test_payments)

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.seed import load
from tests.integration.conftest import assert_error_envelope
from tests.integration.test_payments import (  # noqa: F401 (fake_paystack, packs: fixtures)
    balance,
    charge_success,
    fake_paystack,
    packs,
    webhook,
)
from tests.integration.test_recruiter import _org

API = settings.API_PREFIX


@pytest.fixture
def plans(database):
    with database.begin() as conn:
        load(conn, tables=("subscription_plans",))


async def subscribe(client, who, plan_id: int, **extra):
    return await client.post(
        f"{API}/subscriptions", headers=who["headers"], json={"plan_id": plan_id, **extra}
    )


async def pay(client, fake, checkout: dict, event_id: int = 1):
    amount = fake.amounts[checkout["reference"]]
    response = await webhook(client, charge_success(checkout["reference"], amount, event_id))
    assert response.status_code == 200, response.text


async def my_subscription(client, who):
    response = await client.get(f"{API}/subscriptions/me", headers=who["headers"])
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    return response.json()["data"]


async def test_plans_are_real_and_public(client, plans):
    response = await client.get(f"{API}/subscriptions/plans")
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    found = response.json()["data"]
    assert [(p["plan_id"], p["audience"], p["interval"]) for p in found] == [
        (11, "individual", "monthly"),
        (12, "recruiter", "monthly"),
        (13, "organisation", "yearly"),
    ]
    assert found[0]["price"] == {"amount": 300000, "currency": "NGN"}
    assert found[0]["credits_per_interval"] == 5 and found[0]["seats"] is None
    assert found[2]["seats"] == 50 and found[2]["features"]


async def test_subscribing_is_a_paystack_checkout_and_the_plan_starts_once_paid(
    client, learner, plans, fake_paystack
):
    assert await my_subscription(client, learner) is None
    response = await subscribe(client, learner, 11)
    assert response.status_code == 201, response.text
    assert "X-Sample-Data" not in response.headers
    checkout = response.json()["data"]
    assert checkout["status"] == "pending" and checkout["item_type"] == "subscription_plan"
    assert checkout["item_id"] == 11 and checkout["amount"]["amount"] == 300000
    assert checkout["authorization_url"].startswith("https://checkout.paystack.com/")
    assert await my_subscription(client, learner) is None  # not paid yet

    await pay(client, fake_paystack, checkout)
    sub = await my_subscription(client, learner)
    assert sub["plan_id"] == 11 and sub["plan_name"] == "Individual Monthly"
    assert sub["status"] == "active" and sub["cancel_at_period_end"] is False
    assert sub["seats"] is None
    start = datetime.fromisoformat(sub["current_period_start"])
    end = datetime.fromisoformat(sub["current_period_end"])
    assert abs(start - datetime.now(UTC)) < timedelta(minutes=1)
    assert timedelta(days=28) <= end - start <= timedelta(days=31)
    assert await balance(client, learner) == 5
    credits = (await client.get(f"{API}/credits", headers=learner["headers"])).json()["data"]
    assert credits["transactions"][0]["reason"] == "subscription_grant"
    paid = (
        await client.get(f"{API}/payments/{checkout['reference']}", headers=learner["headers"])
    ).json()["data"]
    assert paid["status"] == "paid" and paid["credits_added"] == 5

    # Paystack retrying the webhook changes nothing
    await pay(client, fake_paystack, checkout)
    assert await balance(client, learner) == 5


async def test_payments_checkout_sells_plans_too(client, learner, plans, fake_paystack):
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "subscription_plan", "item_id": 11},
    )
    assert response.status_code == 201, response.text
    await pay(client, fake_paystack, response.json()["data"])
    assert (await my_subscription(client, learner))["status"] == "active"


async def test_one_plan_at_a_time(client, db, learner, plans, fake_paystack):
    await pay(client, fake_paystack, (await subscribe(client, learner, 11)).json()["data"])
    assert_error_envelope(await subscribe(client, learner, 11), 409, "conflict")
    assert_error_envelope(await subscribe(client, learner, 99), 404, "not_found")
    recruiter = _org(db, "Hire Co", "rita", role="recruiter")
    await pay(client, fake_paystack, (await subscribe(client, recruiter, 11)).json()["data"], 2)
    error = assert_error_envelope(await subscribe(client, recruiter, 12), 409, "conflict")
    assert "cancel" in error["message"]


async def test_cancelling_keeps_the_plan_until_the_period_ends(
    client, db, learner, plans, fake_paystack
):
    url = f"{API}/subscriptions/me/cancel"
    assert_error_envelope(await client.post(url, headers=learner["headers"]), 404, "not_found")
    await pay(client, fake_paystack, (await subscribe(client, learner, 11)).json()["data"])
    response = await client.post(url, headers=learner["headers"])
    assert response.status_code == 200, response.text
    cancelled = response.json()["data"]
    assert cancelled["status"] == "active" and cancelled["cancel_at_period_end"] is True
    again = await client.post(url, headers=learner["headers"])
    assert again.json()["data"]["cancel_at_period_end"] is True
    db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 minute'"))
    db.commit()
    assert (await my_subscription(client, learner))["status"] == "cancelled"
    # a new plan can be bought once the old one has ended
    assert (await subscribe(client, learner, 11)).status_code == 201


async def test_an_organisation_plan_is_for_owners_and_admins_and_gives_seats(
    client, db, learner, plans, fake_paystack
):
    error = assert_error_envelope(await subscribe(client, learner, 13), 403, "forbidden")
    assert "organisation" in error["message"]
    owner = _org(db, "Acme Fintech", "olu", role="owner")
    recruiter = _org(db, "Hire Co", "rita", role="recruiter")
    assert_error_envelope(await subscribe(client, recruiter, 13), 403, "forbidden")

    me = (await client.get(f"{API}/organisations/me", headers=owner["headers"])).json()["data"]
    assert me["seats_total"] == 25
    await pay(client, fake_paystack, (await subscribe(client, owner, 13)).json()["data"])
    sub = await my_subscription(client, owner)
    assert sub["seats"] == 50 and sub["status"] == "active"
    end = datetime.fromisoformat(sub["current_period_end"])
    assert timedelta(days=364) <= end - datetime.fromisoformat(sub["current_period_start"])
    me = (await client.get(f"{API}/organisations/me", headers=owner["headers"])).json()["data"]
    assert me["seats_total"] == 50

    # one organisation plan per organisation, whoever bought it
    admin = _org_admin(db, owner)
    assert_error_envelope(await subscribe(client, admin, 13), 409, "conflict")


async def test_a_recruiter_plan_needs_an_organisation_account(
    client, db, learner, plans, fake_paystack
):
    assert_error_envelope(await subscribe(client, learner, 12), 403, "forbidden")
    recruiter = _org(db, "Hire Co", "rita", role="recruiter")
    assert (await subscribe(client, recruiter, 12)).status_code == 201


async def test_without_a_paystack_key_subscribing_is_unavailable(
    client, learner, plans, monkeypatch
):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "")
    assert_error_envelope(await subscribe(client, learner, 11), 503, "service_unavailable")


def _org_admin(db, owner: dict) -> dict:
    from tests.integration.test_organisation_users import add_learner, headers_for

    learner_id = add_learner(db, "ade")
    db.execute(
        text(
            "INSERT INTO organisation_members (organisation_id, learner_id, role) "
            "VALUES (:o, :l, 'admin')"
        ),
        {"o": owner["id"], "l": learner_id},
    )
    db.commit()
    return {"id": owner["id"], "learner_id": learner_id, "headers": headers_for(db, learner_id)}
