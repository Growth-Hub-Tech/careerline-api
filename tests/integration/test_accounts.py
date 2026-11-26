"""Accounts: sign-up (no email), sign-in, my account, change password, and the reset PIN.

CareerLine sends no email: there is no email confirmation and no reset link.
"""

import pytest

from app.api import API_PREFIX
from tests.integration.conftest import (
    PASSWORD,
    assert_error_envelope,
    login,
    register,
)

API = API_PREFIX
NEW_PASSWORD = "a-brand-new-password"


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def sign_up(client, email="ada@example.com") -> dict:
    response = await register(client, email, full_name="Ada Okafor")
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- Sign-up (no email) ---


async def test_sign_up_signs_in_at_once(client):
    data = await sign_up(client)
    assert set(data) == {"access_token", "token_type", "learner_id"}

    me = await client.get(f"{API}/accounts/me", headers=bearer(data["access_token"]))
    assert me.status_code == 200, me.text
    account = me.json()["data"]
    assert account["email"] == "ada@example.com"
    assert "email_verified" not in account
    assert account["account_type"] == "learner"


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


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/accounts/password-reset"),
        ("POST", "/accounts/verify-email"),
        ("POST", "/accounts/verify-email/resend"),
        ("POST", "/contact"),
        ("GET", "/test-mailbox"),
    ],
)
async def test_the_email_routes_are_gone(client, method, path):
    response = await client.request(method, f"{API}{path}", json={"email": "a@b.co"})
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
