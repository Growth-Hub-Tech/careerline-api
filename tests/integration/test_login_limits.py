"""Day 6: sign-in attempts are limited, and nothing tells whether an email has an account.

Per email address: 5 failed sign-ins in 15 minutes lock that address for the rest of the window
(429 with Retry-After), even with the right password, and an unknown address locks the same way.
Per IP address: 20 failed sign-ins in 15 minutes. Limits are in the database, so they survive a
restart and hold across server processes."""

import time

import pytest

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope, login, register

API = settings.API_PREFIX


@pytest.fixture
async def ada(client):
    response = await register(client, "ada@example.com")
    assert response.status_code == 200, response.text


async def fail(client, email: str, times: int) -> None:
    for _ in range(times):
        response = await login(client, email, password="not-the-password")
        assert response.status_code == 401, response.text


async def test_five_wrong_passwords_lock_the_email_even_for_the_right_password(client, ada):
    await fail(client, "ada@example.com", 5)
    response = await login(client, "ada@example.com")
    error = assert_error_envelope(response, 429, "rate_limited")
    assert 0 < int(response.headers["Retry-After"]) <= 15 * 60
    assert "ada@example.com" not in error["message"]


async def test_an_unknown_email_locks_exactly_like_a_known_one(client, ada):
    await fail(client, "nobody@example.com", 5)
    known = await login(client, "ada@example.com", password="not-the-password")
    unknown = await login(client, "nobody@example.com")
    assert known.status_code == 401
    assert unknown.status_code == 429


async def test_a_successful_sign_in_resets_the_count(client, ada):
    await fail(client, "ada@example.com", 4)
    assert (await login(client, "ada@example.com")).status_code == 200
    await fail(client, "ada@example.com", 4)
    assert (await login(client, "ada@example.com")).status_code == 200


async def test_one_ip_address_gets_twenty_failures_across_all_emails(client, ada):
    for n in range(20):
        await fail(client, f"guess{n}@example.com", 1)
    response = await login(client, "ada@example.com")
    assert_error_envelope(response, 429, "rate_limited")


async def test_wrong_password_and_unknown_email_look_the_same(client, ada):
    wrong = await login(client, "ada@example.com", password="not-the-password")
    unknown = await login(client, "nobody@example.com", password="not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    strip = lambda r: {**r.json()["error"], "request_id": None}  # noqa: E731
    assert strip(wrong) == strip(unknown)


async def test_an_unknown_email_takes_as_long_as_a_wrong_password(client, ada):
    async def timed(email: str) -> float:
        started = time.perf_counter()
        await login(client, email, password="not-the-password")
        return time.perf_counter() - started

    await timed("warm-up@example.com")
    known = min([await timed("ada@example.com") for _ in range(3)])
    unknown = min([await timed(f"nobody{n}@example.com") for n in range(3)])
    # Both check a password hash; without that, an unknown email answers ~10x faster
    assert unknown > known * 0.5, (known, unknown)
