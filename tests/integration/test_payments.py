"""Day 16: Paystack payments, part 1. Credit packs are real; a checkout starts a Paystack
transaction (test mode on the test server); Paystack's webhook, checked with its HMAC signature,
or a check on return (verify) marks the payment paid exactly once and adds the credits.

Paystack is never called: every test answers for it with an httpx mock transport."""

import hashlib
import hmac
import json

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.seed import load
from app.integrations import paystack
from tests.integration.conftest import assert_error_envelope

API = settings.API_PREFIX
SECRET = "paystack-test-secret-for-tests-only"


class FakePaystack:
    """Answers like Paystack's /transaction/initialize and /transaction/verify/{reference}."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.verify_status = "success"
        self.verify_amount: int | None = None  # None: the payment's own amount
        self.fail_initialize = False
        self.amounts: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/transaction/initialize":
            if self.fail_initialize:
                return httpx.Response(500, json={"status": False, "message": "down"})
            body = json.loads(request.content)
            self.amounts[body["reference"]] = body["amount"]
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "message": "Authorization URL created",
                    "data": {
                        "authorization_url": f"https://checkout.paystack.com/{body['reference']}",
                        "access_code": "ac_" + body["reference"][-6:],
                        "reference": body["reference"],
                    },
                },
            )
        if request.url.path.startswith("/transaction/verify/"):
            reference = request.url.path.rsplit("/", 1)[1]
            amount = self.verify_amount
            if amount is None:
                amount = self.amounts.get(reference, 0)
            return httpx.Response(
                200,
                json={
                    "status": True,
                    "data": {
                        "id": 4099260516,
                        "status": self.verify_status,
                        "reference": reference,
                        "amount": amount,
                        "currency": "NGN",
                        "channel": "card",
                        "paid_at": "2026-11-16T10:00:00.000Z",
                    },
                },
            )
        return httpx.Response(404, json={"status": False})

    def calls(self, path_start: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.startswith(path_start)]


@pytest.fixture
def packs(database):
    with database.begin() as conn:
        load(conn, tables=("credit_packs",))


@pytest.fixture
def fake_paystack(monkeypatch, packs) -> FakePaystack:
    fake = FakePaystack()
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", SECRET)
    monkeypatch.setattr(paystack, "TRANSPORT", httpx.MockTransport(fake))
    return fake


def signed(body: dict, secret: str = SECRET) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest()
    return raw, {"x-paystack-signature": signature, "content-type": "application/json"}


def charge_success(reference: str, amount: int, event_id: int = 1) -> dict:
    return {
        "event": "charge.success",
        "data": {
            "id": event_id,
            "reference": reference,
            "status": "success",
            "amount": amount,
            "currency": "NGN",
            "channel": "card",
            "paid_at": "2026-11-16T10:00:00.000Z",
        },
    }


async def checkout(client, learner, pack_id: int = 2, **extra) -> dict:
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "credit_pack", "item_id": pack_id, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def webhook(client, body: dict, secret: str = SECRET):
    raw, headers = signed(body, secret)
    return await client.post(f"{API}/payments/webhooks/paystack", content=raw, headers=headers)


async def balance(client, learner) -> int:
    response = await client.get(f"{API}/credits", headers=learner["headers"])
    assert response.status_code == 200, response.text
    return response.json()["data"]["credits_balance"]


async def test_credit_packs_are_real_and_public(client, packs):
    response = await client.get(f"{API}/payments/credit-packs")
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    assert response.json()["data"] == [
        {
            "pack_id": 1,
            "name": "Starter",
            "credits": 5,
            "price": {"amount": 500000, "currency": "NGN"},
        },
        {
            "pack_id": 2,
            "name": "Standard",
            "credits": 12,
            "price": {"amount": 1000000, "currency": "NGN"},
        },
        {
            "pack_id": 3,
            "name": "Team",
            "credits": 60,
            "price": {"amount": 4500000, "currency": "NGN"},
        },
    ]


async def test_checkout_starts_a_paystack_transaction(client, learner, fake_paystack):
    payment = await checkout(client, learner)
    assert payment["status"] == "pending" and payment["paid_at"] is None
    assert payment["amount"] == {"amount": 1_000_000, "currency": "NGN"}
    assert payment["credits_added"] == 0
    assert payment["item_type"] == "credit_pack" and payment["item_id"] == 2
    assert payment["reference"].startswith("cl_")
    assert payment["authorization_url"] == f"https://checkout.paystack.com/{payment['reference']}"

    (call,) = fake_paystack.calls("/transaction/initialize")
    assert call.headers["authorization"] == f"Bearer {SECRET}"
    sent = json.loads(call.content)
    assert sent["amount"] == 1_000_000 and sent["currency"] == "NGN"
    assert sent["email"] == learner["email"] and sent["reference"] == payment["reference"]
    assert sent["callback_url"] == f"{settings.FRONTEND_URL}/payments/callback"


async def test_a_callback_url_must_be_on_the_website(client, learner, fake_paystack):
    good = await checkout(client, learner, callback_url=f"{settings.FRONTEND_URL}/done?x=1")
    assert json.loads(fake_paystack.requests[-1].content)["callback_url"].endswith("/done?x=1")
    assert good["status"] == "pending"
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "credit_pack", "item_id": 1, "callback_url": "https://evil.example/x"},
    )
    assert_error_envelope(response, 400, "bad_request")


async def test_checkout_of_something_not_for_sale(client, learner, fake_paystack):
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "credit_pack", "item_id": 99},
    )
    assert_error_envelope(response, 404, "not_found")
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "subscription_plan", "item_id": 99},
    )
    assert_error_envelope(response, 404, "not_found")  # plans are on sale since Day 25
    assert fake_paystack.calls("/transaction") == []


async def test_without_a_paystack_key_checkout_is_unavailable(client, learner, packs, monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "")

    def never(request):
        raise AssertionError("Paystack must not be called without a key")

    monkeypatch.setattr(paystack, "TRANSPORT", httpx.MockTransport(never))
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "credit_pack", "item_id": 1},
    )
    assert_error_envelope(response, 503, "service_unavailable")
    raw, headers = signed(charge_success("cl_x", 500000))
    response = await client.post(f"{API}/payments/webhooks/paystack", content=raw, headers=headers)
    assert_error_envelope(response, 503, "service_unavailable")


async def test_paystack_down_at_checkout_is_a_503_and_saves_nothing(
    client, learner, fake_paystack, db
):
    fake_paystack.fail_initialize = True
    response = await client.post(
        f"{API}/payments/checkout",
        headers=learner["headers"],
        json={"item_type": "credit_pack", "item_id": 1},
    )
    assert_error_envelope(response, 503, "service_unavailable")
    assert db.execute(text("SELECT count(*) FROM payments")).scalar() == 0


async def test_the_webhook_pays_once_and_adds_the_credits_once(client, learner, fake_paystack):
    payment = await checkout(client, learner)
    event = charge_success(payment["reference"], 1_000_000)
    first = await webhook(client, event)
    assert first.status_code == 200, first.text
    assert first.json()["data"] == {"received": True}
    again = await webhook(client, event)  # Paystack retries: nothing more happens
    assert again.status_code == 200

    paid = (
        await client.get(f"{API}/payments/{payment['reference']}", headers=learner["headers"])
    ).json()["data"]
    assert paid["status"] == "paid" and paid["paid_at"] and paid["credits_added"] == 12
    assert await balance(client, learner) == 12
    credits = (await client.get(f"{API}/credits", headers=learner["headers"])).json()["data"]
    assert [(t["change"], t["reason"], t["balance_after"]) for t in credits["transactions"]] == [
        (12, "purchase", 12)
    ]
    assert fake_paystack.calls("/transaction/verify") == []  # paid already: no need to ask


async def test_a_new_event_id_for_a_paid_payment_changes_nothing(client, learner, fake_paystack):
    payment = await checkout(client, learner)
    await webhook(client, charge_success(payment["reference"], 1_000_000, event_id=1))
    await webhook(client, charge_success(payment["reference"], 1_000_000, event_id=2))
    assert await balance(client, learner) == 12


@pytest.mark.parametrize("problem", ["no_signature", "wrong_secret", "changed_body"])
async def test_a_webhook_without_a_valid_signature_is_refused(
    client, learner, fake_paystack, problem
):
    payment = await checkout(client, learner)
    event = charge_success(payment["reference"], 1_000_000)
    raw, headers = signed(event, "someone-elses-secret" if problem == "wrong_secret" else SECRET)
    if problem == "no_signature":
        headers.pop("x-paystack-signature")
    if problem == "changed_body":
        raw = raw.replace(b"1000000", b"9000000")
    response = await client.post(f"{API}/payments/webhooks/paystack", content=raw, headers=headers)
    assert_error_envelope(response, 401, "unauthenticated")
    assert await balance(client, learner) == 0


async def test_a_wrong_amount_does_not_pay(client, learner, fake_paystack):
    payment = await checkout(client, learner)
    response = await webhook(client, charge_success(payment["reference"], 100))
    assert response.status_code == 200
    fake_paystack.verify_status = "abandoned"
    detail = (
        await client.get(f"{API}/payments/{payment['reference']}", headers=learner["headers"])
    ).json()["data"]
    assert detail["status"] == "pending"
    assert await balance(client, learner) == 0


async def test_an_unknown_reference_or_other_event_is_acknowledged(client, fake_paystack):
    response = await webhook(client, charge_success("cl_unknown", 500000))
    assert response.status_code == 200 and response.json()["data"] == {"received": True}
    response = await webhook(client, {"event": "transfer.success", "data": {"id": 9}})
    assert response.status_code == 200


async def test_coming_back_from_paystack_checks_the_payment(client, learner, fake_paystack):
    payment = await checkout(client, learner, pack_id=1)
    detail = (
        await client.get(f"{API}/payments/{payment['reference']}", headers=learner["headers"])
    ).json()["data"]
    assert detail["status"] == "paid" and detail["credits_added"] == 5
    assert len(fake_paystack.calls("/transaction/verify")) == 1
    # the webhook arriving later changes nothing
    await webhook(client, charge_success(payment["reference"], 500_000))
    assert await balance(client, learner) == 5


async def test_a_failed_payment_stays_failed(client, learner, fake_paystack):
    payment = await checkout(client, learner, pack_id=1)
    fake_paystack.verify_status = "failed"
    detail = (
        await client.get(f"{API}/payments/{payment['reference']}", headers=learner["headers"])
    ).json()["data"]
    assert detail["status"] == "failed"
    await webhook(client, charge_success(payment["reference"], 500_000))
    assert await balance(client, learner) == 0


async def test_payments_are_private_and_listed_newest_first(
    client, learner, other_learner, fake_paystack
):
    first = await checkout(client, learner, pack_id=1)
    second = await checkout(client, learner, pack_id=3)
    response = await client.get(
        f"{API}/payments/{first['reference']}", headers=other_learner["headers"]
    )
    assert_error_envelope(response, 404, "not_found")
    mine = (await client.get(f"{API}/payments", headers=learner["headers"])).json()["data"]
    assert [p["reference"] for p in mine["items"]] == [second["reference"], first["reference"]]
    assert mine["total"] == 2
    theirs = (await client.get(f"{API}/payments", headers=other_learner["headers"])).json()
    assert theirs["data"]["items"] == [] and theirs["data"]["total"] == 0


async def test_payments_and_credits_need_a_login(client, packs):
    for method, path in [
        ("POST", "/payments/checkout"),
        ("GET", "/payments"),
        ("GET", "/payments/cl_x"),
        ("GET", "/credits"),
    ]:
        response = await client.request(method, f"{API}{path}", json={})
        assert_error_envelope(response, 401, "unauthenticated")
