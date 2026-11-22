"""Accounts: sign-up (no email), sign-in, my account, change password, and the reset PIN.

Email confirmation is switched off but its routes are kept, so they are still tested.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import (
    MAILBOX,
    MAILBOX_TOKEN,
    PASSWORD,
    assert_error_envelope,
    login,
    register,
)

API = settings.API_PREFIX
NEW_PASSWORD = "a-brand-new-password"


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "test_mailbox")
    monkeypatch.setattr(settings, "TEST_MAILBOX_TOKEN", MAILBOX_TOKEN)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.careerline.test")


async def drain():
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


async def emails(client, address: str) -> list[dict]:
    await drain()
    response = await client.get(f"{API}/test-mailbox", params={"to": address}, headers=MAILBOX)
    assert response.status_code == 200, response.text
    return response.json()["data"]["messages"]


def token_from(message: dict, path: str) -> str:
    link = next(link for link in message["links"] if urlparse(link).path == path)
    assert link.startswith("https://app.careerline.test/")
    return parse_qs(urlparse(link).query)["token"][0]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def sign_up(client, email="ada@example.com") -> dict:
    response = await register(client, email, full_name="Ada Okafor")
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- Sign-up (no email) and the switched-off email confirmation ---


async def test_sign_up_signs_in_sends_no_email_and_reports_the_email_as_confirmed(client):
    data = await sign_up(client)
    assert set(data) == {"access_token", "token_type", "learner_id"}

    me = await client.get(f"{API}/accounts/me", headers=bearer(data["access_token"]))
    assert me.status_code == 200, me.text
    account = me.json()["data"]
    assert account["email"] == "ada@example.com"
    assert account["email_verified"] is True
    assert account["account_type"] == "learner"
    assert await emails(client, "ada@example.com") == []


async def resent_token(client, data: dict) -> str:
    response = await client.post(
        f"{API}/accounts/verify-email/resend", headers=bearer(data["access_token"])
    )
    assert response.status_code == 202, response.text
    return token_from((await emails(client, "ada@example.com"))[0], "/verify-email")


async def test_the_kept_confirmation_link_still_works_once(client, db):
    data = await sign_up(client)
    token = await resent_token(client, data)

    response = await client.post(f"{API}/accounts/verify-email", json={"token": token})
    assert response.status_code == 200, response.text
    assert db.execute(text("SELECT email_verified_at FROM learner")).scalar_one() is not None

    again = await client.post(f"{API}/accounts/verify-email", json={"token": token})
    assert_error_envelope(again, 410, "expired")
    made_up = await client.post(f"{API}/accounts/verify-email", json={"token": "made-up-value"})
    assert_error_envelope(made_up, 410, "expired")


async def test_tokens_are_stored_hashed(client, db):
    token = await resent_token(client, await sign_up(client))
    stored = db.execute(text("SELECT token_hash FROM account_tokens")).scalars().all()
    assert stored and token not in stored


async def test_sign_up_emails_are_case_insensitive(client):
    await sign_up(client, "Ada@Example.com")
    response = await register(client, "ada@example.com")
    assert_error_envelope(response, 400, "email_taken")
    assert (await login(client, "ADA@example.com")).status_code == 200


# --- My account ---


async def test_my_account_can_be_updated(client):
    data = await sign_up(client)
    response = await client.patch(
        f"{API}/accounts/me",
        headers=bearer(data["access_token"]),
        json={"full_name": "Ada O.", "phone": "+2348011111111"},
    )
    assert response.status_code == 200, response.text
    account = response.json()["data"]
    assert (account["full_name"], account["phone"]) == ("Ada O.", "+2348011111111")
    assert account["email"] == "ada@example.com"


async def test_my_account_needs_a_login(client):
    assert_error_envelope(await client.get(f"{API}/accounts/me"), 401, "unauthenticated")


async def test_changing_my_password_needs_the_current_one(client):
    data = await sign_up(client)
    response = await client.post(
        f"{API}/accounts/me/password",
        headers=bearer(data["access_token"]),
        json={"current_password": "not-my-password", "new_password": NEW_PASSWORD},
    )
    assert_error_envelope(response, 400, "wrong_password")

    response = await client.post(
        f"{API}/accounts/me/password",
        headers=bearer(data["access_token"]),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert (await login(client, "ada@example.com", NEW_PASSWORD)).status_code == 200
    assert (await login(client, "ada@example.com", PASSWORD)).status_code == 401
    subjects = [m["subject"] for m in await emails(client, "ada@example.com")]
    assert any("password was changed" in s.lower() for s in subjects)


# --- Forgot password: the fixed reset PIN ---


async def reset(client, email="ada@example.com", pin="1234", password=NEW_PASSWORD):
    return await client.post(
        f"{API}/accounts/password-reset/confirm",
        json={"email": email, "pin": pin, "new_password": password},
    )


async def test_the_reset_pin_sets_a_new_password(client):
    await sign_up(client)
    response = await reset(client, email="ADA@example.com")
    assert response.status_code == 200, response.text
    assert (await login(client, "ada@example.com", NEW_PASSWORD)).status_code == 200
    assert (await login(client, "ada@example.com", PASSWORD)).status_code == 401


async def test_a_wrong_pin_and_an_unknown_email_get_the_same_answer(client):
    await sign_up(client)
    wrong = await reset(client, pin="0000")
    unknown = await reset(client, email="nobody@example.com")
    assert_error_envelope(wrong, 400, "invalid_reset_pin")
    assert_error_envelope(unknown, 400, "invalid_reset_pin")
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert (await login(client, "ada@example.com")).status_code == 200


async def test_five_wrong_pins_lock_the_reset_even_with_the_right_pin(client):
    await sign_up(client)
    for _ in range(5):
        assert (await reset(client, pin="9999")).status_code == 400
    locked = await reset(client)
    assert_error_envelope(locked, 429, "rate_limited")
    assert int(locked.headers["Retry-After"]) > 0
    assert (await login(client, "ada@example.com")).status_code == 200


async def test_a_reset_clears_a_sign_in_lockout(client):
    await sign_up(client)
    for _ in range(5):
        await login(client, "ada@example.com", "wrong-password")
    assert (await login(client, "ada@example.com", NEW_PASSWORD)).status_code == 429
    assert (await reset(client)).status_code == 200
    assert (await login(client, "ada@example.com", NEW_PASSWORD)).status_code == 200


async def test_the_old_reset_request_route_is_gone(client):
    response = await client.post(f"{API}/accounts/password-reset", json={"email": "a@b.co"})
    assert response.status_code in (404, 405)


async def test_five_wrong_current_passwords_lock_the_password_change(client):
    data = await sign_up(client)
    body = {"current_password": "not-my-password", "new_password": NEW_PASSWORD}
    for _ in range(5):
        response = await client.post(
            f"{API}/accounts/me/password", headers=bearer(data["access_token"]), json=body
        )
        assert_error_envelope(response, 400, "wrong_password")
    response = await client.post(
        f"{API}/accounts/me/password",
        headers=bearer(data["access_token"]),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert_error_envelope(response, 429, "rate_limited")
