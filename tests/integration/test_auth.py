from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt
from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import PASSWORD, assert_error_envelope, login, register

API = settings.API_PREFIX


async def test_readyz_is_ready_on_the_migrated_database(client):
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["data"] == {"status": "ready"}


async def test_register_returns_a_token_that_works(client):
    response = await register(client, "new@example.com", full_name="New Learner")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["token_type"] == "bearer"
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = await client.get(f"{API}/learners/{data['learner_id']}", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["learner"]["email"] == "new@example.com"


async def test_password_is_stored_hashed(client, db):
    await register(client, "hash@example.com")

    stored = db.execute(
        text("SELECT hashed_password FROM learner WHERE email = 'hash@example.com'")
    ).scalar_one()
    assert stored != PASSWORD
    assert stored.startswith("$2b$")


async def test_login_with_the_oauth2_form_returns_a_plain_token_body(client, learner):
    response = await login(client, learner["email"])

    assert response.status_code == 200
    body = response.json()
    # Not wrapped in the envelope, so /docs "Authorize" and OAuth2 clients can read it
    assert set(body) == {"access_token", "token_type", "learner_id", "full_name"}
    assert body["token_type"] == "bearer"
    assert body["learner_id"] == learner["learner_id"]


async def test_wrong_password_is_401(client, learner):
    response = await login(client, learner["email"], password="not-the-password")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_unknown_email_gets_the_same_401_as_a_wrong_password(client, learner):
    wrong_password = await login(client, learner["email"], password="not-the-password")
    unknown_email = await login(client, "nobody@example.com")

    assert unknown_email.status_code == 401
    assert unknown_email.json()["error"]["message"] == wrong_password.json()["error"]["message"]


async def test_registering_the_same_email_twice_is_400(client, learner):
    response = await register(client, learner["email"])

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Email already registered"


async def test_protected_route_without_a_token_is_401(client, learner):
    response = await client.get(f"{API}/learners/{learner['learner_id']}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_garbage_token_is_401(client, learner):
    headers = {"Authorization": "Bearer not.a.token"}
    response = await client.get(f"{API}/learners/{learner['learner_id']}", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_expired_token_is_401(client, learner):
    expired = jwt.encode(
        {"sub": str(learner["learner_id"]), "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {expired}"}
    response = await client.get(f"{API}/learners/{learner['learner_id']}", headers=headers)

    assert response.status_code == 401


async def test_token_signed_with_another_key_is_401(client, learner):
    forged = jwt.encode({"sub": str(learner["learner_id"])}, "some-other-key", algorithm="HS256")
    headers = {"Authorization": f"Bearer {forged}"}
    response = await client.get(f"{API}/learners/{learner['learner_id']}", headers=headers)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("empty@example.com", ""),
        ("short@example.com", "1234567"),
        ("not-an-email", "long-enough-password"),
    ],
)
async def test_register_rejects_a_bad_email_or_weak_password(client, db, email, password):
    response = await register(client, email, password=password)

    assert_error_envelope(response, 422, "validation_error")
    created = db.execute(
        text("SELECT count(*) FROM learner WHERE email = :email"), {"email": email}
    ).scalar_one()
    assert created == 0


async def test_old_signup_route_does_not_create_passwordless_accounts(client, db):
    response = await client.post(
        f"{API}/learners/register",
        json={"full_name": "No Password", "email": "nopass@example.com", "phone": "1"},
    )

    created = db.execute(
        text("SELECT count(*) FROM learner WHERE email = 'nopass@example.com'")
    ).scalar_one()
    assert created == 0, f"route answered {response.status_code} and created a learner"


async def test_old_signup_route_does_not_reveal_an_existing_learners_id(client, learner):
    response = await client.post(
        f"{API}/learners/register",
        json={"full_name": "Someone Else", "email": learner["email"], "phone": "1"},
    )

    assert response.status_code != 200
    assert str(learner["learner_id"]) not in str(response.json().get("data"))
