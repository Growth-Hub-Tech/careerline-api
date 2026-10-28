"""Day 6: sessions are revocable. Sign-out ends one session; a password reset ends all of them;
a password change ends all the others."""

import pytest
from jose import jwt

from app.core.config import settings
from app.jobs.runner import JobRunner
from tests.integration.conftest import PASSWORD, assert_error_envelope, login, register

API = settings.API_PREFIX


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "test_mailbox")
    monkeypatch.setattr(settings, "TEST_MAILBOX_TOKEN", "")


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def two_sessions(client) -> tuple[dict, dict]:
    await register(client, "ada@example.com")
    phone = (await login(client, "ada@example.com")).json()["access_token"]
    laptop = (await login(client, "ada@example.com")).json()["access_token"]
    return bearer(phone), bearer(laptop)


async def works(client, headers) -> bool:
    response = await client.get(f"{API}/accounts/me", headers=headers)
    assert response.status_code in (200, 401), response.text
    return response.status_code == 200


async def test_sign_out_ends_this_session_only(client):
    phone, laptop = await two_sessions(client)
    response = await client.post(f"{API}/auth/logout", headers=phone)
    assert response.status_code == 200, response.text
    assert not await works(client, phone)
    assert await works(client, laptop)
    # Signing out twice is fine for the app, but the token stays dead
    assert_error_envelope(
        await client.post(f"{API}/auth/logout", headers=phone), 401, "unauthenticated"
    )


async def test_sign_out_everywhere_ends_every_session(client):
    phone, laptop = await two_sessions(client)
    response = await client.post(f"{API}/auth/logout", headers=phone, params={"everywhere": "true"})
    assert response.status_code == 200, response.text
    assert not await works(client, phone)
    assert not await works(client, laptop)


async def test_a_password_reset_ends_every_session(client):
    phone, laptop = await two_sessions(client)
    await client.post(f"{API}/accounts/password-reset", json={"email": "ada@example.com"})
    runner = JobRunner(worker_id="test")
    while await runner.run_once():
        pass
    mail = await client.get(f"{API}/test-mailbox", params={"to": "ada@example.com"})
    reset = next(m for m in mail.json()["data"]["messages"] if "reset" in m["subject"].lower())
    token = reset["links"][0].split("token=")[1]
    response = await client.post(
        f"{API}/accounts/password-reset/confirm",
        json={"token": token, "new_password": "new-password-1"},
    )
    assert response.status_code == 200, response.text
    assert not await works(client, phone)
    assert not await works(client, laptop)


async def test_changing_the_password_ends_the_other_sessions(client):
    phone, laptop = await two_sessions(client)
    response = await client.post(
        f"{API}/accounts/me/password",
        headers=phone,
        json={"current_password": PASSWORD, "new_password": "new-password-1"},
    )
    assert response.status_code == 200, response.text
    assert await works(client, phone)
    assert not await works(client, laptop)


async def test_a_token_from_before_sessions_existed_is_refused(client):
    # Tokens issued before Day 6 have no session id: they must log in again
    response = await register(client, "ada@example.com")
    learner_id = response.json()["data"]["learner_id"]
    old_style = jwt.encode(
        {"sub": str(learner_id), "exp": 9999999999}, settings.SECRET_KEY, algorithm="HS256"
    )
    assert not await works(client, bearer(old_style))


async def test_a_session_of_another_account_cannot_be_borrowed(client, db):
    phone, _ = await two_sessions(client)
    await register(client, "bola@example.com")
    bola_id = (await login(client, "bola@example.com")).json()["learner_id"]
    # Same session id, another learner id in the token (needs the secret key, but checked anyway)
    claims = jwt.decode(
        phone["Authorization"].split()[1], settings.SECRET_KEY, algorithms=["HS256"]
    )
    swapped = jwt.encode({**claims, "sub": str(bola_id)}, settings.SECRET_KEY, algorithm="HS256")
    assert not await works(client, bearer(swapped))
