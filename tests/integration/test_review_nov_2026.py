"""Review, November 2026: tests for the bugs found in the bug hunt.

Each test states the correct behaviour. Run against the code before the fix, they fail; the
fix in the same commit makes them pass.
"""

from app.core.config import settings
from app.services import account_service
from tests.integration.conftest import PASSWORD, assert_error_envelope, login, take_test

API = settings.API_PREFIX


async def test_out_of_range_paging_on_my_attempts_is_refused_not_a_server_error(client, learner):
    # a limit outside 1-100 or a negative offset is a bad request (422 from the paging check)
    for query in ("limit=-1", "offset=-1", "limit=0", "limit=101"):
        response = await client.get(f"{API}/attempts/me?{query}", headers=learner["headers"])
        assert response.status_code == 422, (query, response.status_code, response.text)


async def test_attempt_history_total_is_the_whole_count_not_the_page(client, learner, skill):
    for _ in range(2):
        await take_test(client, learner["headers"], skill)
    page = await client.get(f"{API}/attempts/me?limit=1", headers=learner["headers"])
    body = page.json()["data"]
    assert len(body["attempts"]) == 1
    assert body["total"] == 2, body["total"]


# ---------- sign-up and account field limits (the learner table's column sizes) ----------

GOOD = {"full_name": "Ada Learner", "phone": "08000000000", "password": "long-enough-1"}


def email_of(length: int) -> str:
    return "a" * (length - len("@example.com")) + "@example.com"


async def sign_up(client, **changes):
    body = {**GOOD, "email": email_of(30), **changes}
    return await client.post(f"{API}/auth/register", json=body)


async def test_sign_up_accepts_values_that_fill_each_column(client):
    response = await sign_up(
        client,
        full_name="N" * 100,
        email=email_of(100),
        phone="0" * 20,
        password="p" * 128,
    )
    assert response.status_code == 200, response.text


async def test_sign_up_refuses_values_longer_than_their_column_with_a_422(client):
    for field, value in (
        ("full_name", "N" * 101),
        ("full_name", ""),
        ("email", email_of(101)),
        ("phone", "0" * 21),
        ("password", "p" * 129),
    ):
        response = await sign_up(client, **{field: value})
        assert response.status_code == 422, (field, len(value), response.text)


async def test_account_changes_longer_than_their_column_are_a_422_not_a_500(client, learner):
    for change in ({"full_name": "N" * 101}, {"phone": "0" * 21}):
        response = await client.patch(f"{API}/accounts/me", json=change, headers=learner["headers"])
        assert response.status_code == 422, (change, response.text)
    response = await client.patch(
        f"{API}/accounts/me",
        json={"full_name": "N" * 100, "phone": "0" * 20},
        headers=learner["headers"],
    )
    assert response.status_code == 200, response.text


async def test_every_password_field_refuses_more_than_128_characters(client, learner):
    long = "p" * 129
    for path, body in (
        ("/accounts/me/password", {"current_password": long, "new_password": "long-enough-1"}),
        ("/accounts/me/password", {"current_password": PASSWORD, "new_password": long}),
        ("/accounts/password-reset/confirm", {"token": "anything", "new_password": long}),
        ("/privacy/account-deletion", {"password": long}),
    ):
        response = await client.post(f"{API}{path}", json=body, headers=learner["headers"])
        assert response.status_code == 422, (path, response.text)


async def test_a_sign_in_with_a_huge_password_fails_without_hashing_it(
    client, learner, monkeypatch
):
    def must_not_hash(*args):
        raise AssertionError("an over-long password was hashed")

    monkeypatch.setattr(account_service, "verify_password", must_not_hash)
    monkeypatch.setattr(account_service, "burn_password_check", must_not_hash)
    for _ in range(5):
        response = await login(client, learner["email"], password="p" * 129)
        assert response.status_code == 401, response.text
    # each one counted as a failed sign-in, like any wrong password
    response = await login(client, learner["email"], password="p" * 129)
    assert_error_envelope(response, 429, "rate_limited")
