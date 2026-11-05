"""Day 26: subscriptions part 2: renewals.

The card of the first payment (Paystack's reusable authorization) is charged again an hour before
each period ends (a background job, POST /transaction/charge_authorization). Paid: the next period
starts where the last one ended and its credits are added. Not paid (declined, or no reusable
card): the person gets an email to pay again with POST /subscriptions; the card is tried again
the next day, up to SUBSCRIPTION_RENEW_ATTEMPTS; the plan is past_due after its period, then
cancelled after the grace days. A cancelled plan is never charged. An ended organisation plan
gives its seats back.
"""

# ruff: noqa: F811 (pytest fixtures imported from test_payments)

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.integrations import paystack
from app.jobs.runner import JobRunner
from tests.integration.test_payments import (  # noqa: F401 (packs: a fixture)
    SECRET,
    FakePaystack,
    balance,
    charge_success,
    packs,
    webhook,
)
from tests.integration.test_recruiter import _org
from tests.integration.test_subscriptions import my_subscription, plans, subscribe  # noqa: F401

API = settings.API_PREFIX
AUTH = {"authorization_code": "AUTH_test123", "reusable": True, "channel": "card"}


class RenewingPaystack(FakePaystack):
    """Also answers /transaction/charge_authorization (status: success, failed, ...)."""

    def __init__(self):
        super().__init__()
        self.charge_status = "success"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/transaction/charge_authorization":
            self.requests.append(request)
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "message": "Charge attempted",
                    "data": {
                        "id": 5100000000 + len(self.requests),
                        "status": self.charge_status,
                        "reference": body["reference"],
                        "amount": body["amount"],
                        "currency": "NGN",
                        "channel": "card",
                    },
                },
            )
        return super().__call__(request)


@pytest.fixture
def fake(monkeypatch, packs) -> RenewingPaystack:  # noqa: F811
    fake = RenewingPaystack()
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "test_mailbox")
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", SECRET)
    monkeypatch.setattr(paystack, "TRANSPORT", httpx.MockTransport(fake))
    return fake


async def run_jobs() -> None:
    runner = JobRunner(worker_id="test", retry_base_seconds=60)
    while await runner.run_once():
        pass


def renew_jobs(db) -> list:
    return db.execute(
        text(
            "SELECT payload, run_after, status FROM background_jobs "
            "WHERE kind = 'renew_subscription' ORDER BY id"
        )
    ).all()


def make_due(db, period_end_in: timedelta = timedelta(minutes=30)) -> None:
    """The period ends soon and its renewal job is due now."""
    db.execute(
        text("UPDATE subscriptions SET current_period_end = now() + :d"), {"d": period_end_in}
    )
    db.execute(
        text(
            "UPDATE background_jobs SET run_after = now(), "
            "payload = jsonb_set(payload, '{period_end}', to_jsonb("
            "(SELECT current_period_end FROM subscriptions ORDER BY id DESC LIMIT 1)::text)) "
            "WHERE kind = 'renew_subscription' AND status = 'queued'"
        )
    )
    db.commit()


async def subscribed(client, who, fake, plan_id: int = 11, authorization=AUTH) -> dict:
    checkout = (await subscribe(client, who, plan_id)).json()["data"]
    event_id = 9000 + len(fake.requests)  # Paystack's event ids are unique
    event = charge_success(checkout["reference"], fake.amounts[checkout["reference"]], event_id)
    if authorization:
        event["data"]["authorization"] = authorization
    assert (await webhook(client, event)).status_code == 200
    return await my_subscription(client, who)


async def test_a_paid_plan_schedules_its_renewal_an_hour_before_the_period_ends(
    client, db, learner, plans, fake
):
    sub = await subscribed(client, learner, fake)
    (job,) = renew_jobs(db)
    assert job.payload["subscription_id"] == sub["subscription_id"]
    end = datetime.fromisoformat(sub["current_period_end"])
    assert abs(job.run_after - (end - timedelta(hours=1))) < timedelta(seconds=2)
    stored = db.execute(text("SELECT authorization_code FROM subscriptions")).scalar()
    assert stored == "AUTH_test123"


async def test_the_renewal_charges_the_card_and_starts_the_next_period(
    client, db, learner, plans, fake
):
    await subscribed(client, learner, fake)
    make_due(db)
    before = await my_subscription(client, learner)
    await run_jobs()

    (charge,) = fake.calls("/transaction/charge_authorization")
    sent = json.loads(charge.content)
    assert sent["authorization_code"] == "AUTH_test123"
    assert sent["email"] == learner["email"] and sent["amount"] == 300000
    after = await my_subscription(client, learner)
    assert after["status"] == "active" and after["subscription_id"] == before["subscription_id"]
    assert after["current_period_start"] == before["current_period_end"]
    assert datetime.fromisoformat(after["current_period_end"]) - datetime.fromisoformat(
        before["current_period_end"]
    ) >= timedelta(days=28)
    assert await balance(client, learner) == 10
    payments = (await client.get(f"{API}/payments", headers=learner["headers"])).json()["data"]
    assert [p["status"] for p in payments["items"]] == ["paid", "paid"]
    assert payments["items"][0]["description"] == "Individual Monthly subscription (renewal)"
    # the next renewal is scheduled; running the jobs again charges nothing more
    jobs = renew_jobs(db)
    assert [j.status for j in jobs] == ["succeeded", "queued"]
    await run_jobs()
    assert len(fake.calls("/transaction/charge_authorization")) == 1


async def test_a_declined_renewal_emails_the_person_and_tries_again_the_next_day(
    client, db, learner, plans, fake
):
    await subscribed(client, learner, fake)
    fake.charge_status = "failed"
    make_due(db)
    await run_jobs()
    assert (await my_subscription(client, learner))["status"] == "active"  # until the period ends
    assert await balance(client, learner) == 5
    mail = db.execute(
        text(
            "SELECT subject, text_body FROM test_mailbox_messages WHERE subject LIKE '%could not be renewed'"
        )
    ).one()
    assert "Individual Monthly" in mail.subject
    assert f"{settings.FRONTEND_URL}/subscription" in mail.text_body
    jobs = renew_jobs(db)
    assert jobs[-1].status == "queued" and jobs[-1].payload["attempt"] == 2
    assert jobs[-1].run_after - datetime.now(UTC) > timedelta(hours=23)

    # the period ends unpaid: past_due; paying again renews it from now
    db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 hour'"))
    db.commit()
    assert (await my_subscription(client, learner))["status"] == "past_due"
    fake.charge_status = "success"
    renewed = await subscribed(client, learner, fake, authorization=None)
    assert renewed["status"] == "active"
    start = datetime.fromisoformat(renewed["current_period_start"])
    assert abs(start - datetime.now(UTC)) < timedelta(minutes=1)
    assert await balance(client, learner) == 10


async def test_after_the_last_attempt_the_card_is_not_tried_again(
    client, db, learner, plans, fake, monkeypatch
):
    monkeypatch.setattr(settings, "SUBSCRIPTION_RENEW_ATTEMPTS", 2)
    await subscribed(client, learner, fake)
    fake.charge_status = "failed"
    for _ in range(3):
        make_due(db, timedelta(minutes=-10))
        await run_jobs()
    assert len(fake.calls("/transaction/charge_authorization")) == 2
    assert [j.status for j in renew_jobs(db)] == ["succeeded", "succeeded"]
    count = db.execute(
        text("SELECT count(*) FROM email_outbox WHERE template = 'subscription_payment_failed'")
    ).scalar()
    assert count == 1  # one email, not one per attempt


async def test_without_a_reusable_card_the_person_is_asked_to_pay(client, db, learner, plans, fake):
    await subscribed(
        client, learner, fake, authorization={"authorization_code": "AUTH_x", "reusable": False}
    )
    make_due(db)
    await run_jobs()
    assert fake.calls("/transaction/charge_authorization") == []
    mail = db.execute(
        text(
            "SELECT text_body FROM test_mailbox_messages WHERE subject LIKE '%could not be renewed'"
        )
    ).scalar()
    assert "/subscription" in mail


async def test_a_cancelled_plan_is_not_renewed(client, db, learner, plans, fake):
    await subscribed(client, learner, fake)
    await client.post(f"{API}/subscriptions/me/cancel", headers=learner["headers"])
    make_due(db)
    await run_jobs()
    assert fake.calls("/transaction/charge_authorization") == []
    assert (
        db.execute(
            text("SELECT count(*) FROM email_outbox WHERE template LIKE 'subscription%'")
        ).scalar()
        == 0
    )
    db.execute(text("UPDATE subscriptions SET current_period_end = now() - interval '1 minute'"))
    db.commit()
    assert (await my_subscription(client, learner))["status"] == "cancelled"


async def test_an_ended_organisation_plan_gives_its_seats_back(client, db, plans, fake):
    owner = _org(db, "Acme Fintech", "olu", role="owner")
    await subscribed(client, owner, fake, plan_id=13)
    me = (await client.get(f"{API}/organisations/me", headers=owner["headers"])).json()["data"]
    assert me["seats_total"] == 50
    db.execute(
        text(
            "UPDATE subscriptions SET current_period_end = now() - interval '4 days', "
            "cancel_at_period_end = false"
        )
    )
    db.commit()
    me = (await client.get(f"{API}/organisations/me", headers=owner["headers"])).json()["data"]
    assert me["seats_total"] == 25
    assert (await my_subscription(client, owner))["status"] == "cancelled"


async def test_a_renewal_paid_by_webhook_later_counts_once(client, db, learner, plans, fake):
    await subscribed(client, learner, fake)
    fake.charge_status = "pending"  # Paystack is still processing it
    make_due(db)
    await run_jobs()
    pending = db.execute(
        text("SELECT reference, amount FROM payments WHERE status = 'pending'")
    ).one()
    for event_id in (77, 77, 78):
        await webhook(client, charge_success(pending.reference, pending.amount, event_id))
    assert await balance(client, learner) == 10
    assert (await my_subscription(client, learner))["status"] == "active"


async def test_when_paystack_does_not_answer_the_renewal_is_tried_again_later(
    client, db, learner, plans, fake, monkeypatch
):
    await subscribed(client, learner, fake)
    make_due(db)

    def down(request):
        return httpx.Response(500, json={"status": False, "message": "down"})

    monkeypatch.setattr(paystack, "TRANSPORT", httpx.MockTransport(down))
    await run_jobs()
    # nothing is known about the charge: nothing is recorded and the job runs again later
    assert db.execute(text("SELECT count(*) FROM payments")).scalar() == 1
    job = renew_jobs(db)[-1]
    assert job.status == "queued" and job.run_after > datetime.now(UTC)
    assert await balance(client, learner) == 5
    assert (await my_subscription(client, learner))["status"] == "active"
    # the same renewal uses the same reference, so Paystack can never charge it twice
    monkeypatch.setattr(paystack, "TRANSPORT", httpx.MockTransport(fake))
    make_due(db)
    await run_jobs()
    references = [json.loads(r.content)["reference"] for r in fake.calls("/transaction/charge")]
    assert len(references) == 1 and references[0].startswith("cl_renew_")


async def test_a_deleted_account_is_never_charged_again(client, db, database, learner, plans, fake):
    from tests.integration.test_privacy import _ask_deletion, _make_due

    await subscribed(client, learner, fake)
    assert (await _ask_deletion(client, learner)).status_code in (200, 202)
    await _make_due(database, learner)
    await run_jobs()
    row = db.execute(
        text("SELECT status, authorization_code, cancel_at_period_end FROM subscriptions")
    ).one()
    assert row.status == "cancelled" and row.authorization_code is None
    make_due(db)
    await run_jobs()
    assert fake.calls("/transaction/charge_authorization") == []


async def test_the_data_export_lists_subscriptions(db, learner, client, plans, fake):
    from app.db.session import AsyncSessionLocal
    from app.services.privacy import build_export

    await subscribed(client, learner, fake)
    async with AsyncSessionLocal() as session:
        data = await build_export(session, learner["learner_id"])
    (sub,) = data["subscriptions"]
    assert sub["plan_name"] == "Individual Monthly" and sub["status"] == "active"
    assert "authorization_code" not in sub
