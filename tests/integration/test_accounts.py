"""Day 6: real accounts, matching the published contract.

Sign-up (POST /auth/register, unchanged), email confirmation (a link in an email, through the
Day 5 email jobs), sign-in (POST /auth/login, unchanged), my account (GET/PATCH /accounts/me),
change password, forgot and reset password. Tokens in links are single-use and expire.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import PASSWORD, assert_error_envelope, login, register

API = settings.API_PREFIX
NEW_PASSWORD = "a-brand-new-password"


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "test_mailbox")
    monkeypatch.setattr(settings, "TEST_MAILBOX_TOKEN", "")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.careerline.test")


async def drain():
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass


async def emails(client, address: str) -> list[dict]:
    await drain()
    response = await client.get(f"{API}/test-mailbox", params={"to": address})
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


# --- Sign-up and email confirmation ---


async def test_sign_up_keeps_the_published_answer_and_sends_a_confirmation_email(client):
    data = await sign_up(client)
    assert set(data) == {"access_token", "token_type", "learner_id"}

    me = await client.get(f"{API}/accounts/me", headers=bearer(data["access_token"]))
    assert me.status_code == 200, me.text
    account = me.json()["data"]
    assert account["email"] == "ada@example.com"
    assert account["email_verified"] is False
    assert account["account_type"] == "learner"
    assert "X-Sample-Data" not in me.headers

    (mail,) = await emails(client, "ada@example.com")
    assert "confirm" in mail["subject"].lower()
    assert token_from(mail, "/verify-email")


async def test_the_confirmation_link_confirms_the_email_once(client):
    data = await sign_up(client)
    token = token_from((await emails(client, "ada@example.com"))[0], "/verify-email")

    response = await client.post(f"{API}/accounts/verify-email", json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"status": "accepted"}
    me = await client.get(f"{API}/accounts/me", headers=bearer(data["access_token"]))
    assert me.json()["data"]["email_verified"] is True

    again = await client.post(f"{API}/accounts/verify-email", json={"token": token})
    assert_error_envelope(again, 410, "expired")


async def test_an_old_or_made_up_confirmation_link_is_410(client, db):
    await sign_up(client)
    token = token_from((await emails(client, "ada@example.com"))[0], "/verify-email")
    db.execute(text("UPDATE account_tokens SET expires_at = now() - interval '1 minute'"))
    db.commit()
    assert_error_envelope(
        await client.post(f"{API}/accounts/verify-email", json={"token": token}), 410, "expired"
    )
    assert_error_envelope(
        await client.post(f"{API}/accounts/verify-email", json={"token": "made-up-token-value"}),
        410,
        "expired",
    )


async def test_resend_sends_a_new_link_and_the_old_one_stops_working(client):
    data = await sign_up(client)
    first = token_from((await emails(client, "ada@example.com"))[0], "/verify-email")

    response = await client.post(
        f"{API}/accounts/verify-email/resend", headers=bearer(data["access_token"])
    )
    assert response.status_code == 202, response.text
    newest = (await emails(client, "ada@example.com"))[0]
    second = token_from(newest, "/verify-email")
    assert second != first

    assert_error_envelope(
        await client.post(f"{API}/accounts/verify-email", json={"token": first}), 410, "expired"
    )
    ok = await client.post(f"{API}/accounts/verify-email", json={"token": second})
    assert ok.status_code == 200, ok.text


async def test_tokens_are_stored_hashed(client, db):
    await sign_up(client)
    token = token_from((await emails(client, "ada@example.com"))[0], "/verify-email")
    stored = db.execute(text("SELECT token_hash FROM account_tokens")).scalars().all()
    assert stored and token not in stored


async def test_sign_up_emails_are_case_insensitive(client):
    await sign_up(client, "Ada@Example.com")
    response = await register(client, "ada@example.com")
    assert_error_envelope(response, 400, "bad_request")
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


# --- Forgot and reset password ---


async def test_forgot_password_sends_a_reset_link_that_works_once(client):
    await sign_up(client)
    response = await client.post(
        f"{API}/accounts/password-reset", json={"email": "ADA@example.com"}
    )
    assert response.status_code == 202, response.text
    assert response.json()["data"] == {"status": "accepted"}

    reset = next(
        m for m in await emails(client, "ada@example.com") if "reset" in m["subject"].lower()
    )
    token = token_from(reset, "/reset-password")
    response = await client.post(
        f"{API}/accounts/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert (await login(client, "ada@example.com", NEW_PASSWORD)).status_code == 200

    again = await client.post(
        f"{API}/accounts/password-reset/confirm", json={"token": token, "new_password": "x" * 12}
    )
    assert_error_envelope(again, 410, "expired")


async def test_a_reset_link_expires_after_an_hour(client, db):
    await sign_up(client)
    await client.post(f"{API}/accounts/password-reset", json={"email": "ada@example.com"})
    reset = next(
        m for m in await emails(client, "ada@example.com") if "reset" in m["subject"].lower()
    )
    token = token_from(reset, "/reset-password")
    expires = db.execute(
        text("SELECT expires_at FROM account_tokens WHERE purpose = 'password_reset'")
    ).scalar_one()
    assert expires <= datetime.now(UTC) + timedelta(minutes=61)
    db.execute(text("UPDATE account_tokens SET expires_at = now() - interval '1 second'"))
    db.commit()
    response = await client.post(
        f"{API}/accounts/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert_error_envelope(response, 410, "expired")


async def test_a_confirmation_token_cannot_reset_a_password(client):
    await sign_up(client)
    verify = token_from((await emails(client, "ada@example.com"))[0], "/verify-email")
    response = await client.post(
        f"{API}/accounts/password-reset/confirm",
        json={"token": verify, "new_password": NEW_PASSWORD},
    )
    assert_error_envelope(response, 410, "expired")


async def test_forgot_password_answers_the_same_whether_or_not_the_email_exists(client, db):
    await sign_up(client)
    known = await client.post(f"{API}/accounts/password-reset", json={"email": "ada@example.com"})
    unknown = await client.post(
        f"{API}/accounts/password-reset", json={"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    # Only the real account gets an email
    assert await emails(client, "nobody@example.com") == []
    assert any("reset" in m["subject"].lower() for m in await emails(client, "ada@example.com"))
