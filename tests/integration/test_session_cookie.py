"""The website's session: an HttpOnly cookie set at sign-in, checked against CSRF by Origin.

The browser fixture talks https, so httpx keeps and sends the Secure cookie the way a browser does.
"""

import httpx
import pytest

from app.core.config import settings
from app.core.security import SESSION_COOKIE
from app.main import app
from tests.integration.conftest import PASSWORD, login, register

API = settings.API_PREFIX
FOREIGN = "https://evil.example"
CONTACT = {
    "full_name": "Ada Okafor",
    "email": "ada@example.com",
    "topic": "general",
    "message": "Hello there, a question about the audits.",
}


@pytest.fixture
async def browser():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
        yield client


@pytest.fixture
def site() -> str:
    return settings.CORS_ORIGINS[0]


async def signed_in(browser, email: str = "ada@example.com") -> httpx.Response:
    assert (await register(browser, email)).status_code == 200
    browser.cookies.clear()  # only the sign-in sets the cookie
    response = await login(browser, email)
    assert response.status_code == 200, response.text
    return response


def cookie_header(response: httpx.Response) -> str:
    (header,) = [h for h in response.headers.get_list("set-cookie") if SESSION_COOKIE in h]
    return header


async def test_signing_in_sets_an_httponly_secure_cookie_as_long_lived_as_the_token(browser):
    response = await signed_in(browser)
    header = cookie_header(response).lower()
    assert f"{SESSION_COOKIE}={response.json()['access_token']}".lower() in header
    for attribute in ("httponly", "secure", "path=/", "max-age=86400", "samesite=lax"):
        assert attribute in header, attribute


async def test_the_test_server_can_send_it_across_sites(browser, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_COOKIE_SAMESITE", "none")
    assert "samesite=none" in cookie_header(await signed_in(browser)).lower()


async def test_the_cookie_alone_signs_in_a_read(browser):
    await signed_in(browser)
    response = await browser.get(f"{API}/accounts/me")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["email"] == "ada@example.com"


async def test_a_change_with_the_cookie_needs_the_websites_origin(browser, site):
    await signed_in(browser)
    change = {"full_name": "Ada From The Site"}
    for headers in ({}, {"Origin": FOREIGN}, {"Origin": "null"}):
        response = await browser.patch(f"{API}/accounts/me", json=change, headers=headers)
        assert response.status_code == 401, (headers, response.text)
    response = await browser.patch(f"{API}/accounts/me", json=change, headers={"Origin": site})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["full_name"] == "Ada From The Site"


async def test_another_sites_cookie_request_to_a_public_route_is_simply_anonymous(browser):
    await signed_in(browser)
    response = await browser.post(f"{API}/contact", json=CONTACT, headers={"Origin": FOREIGN})
    assert response.status_code == 201, response.text


async def test_a_bearer_token_wins_over_the_cookie(browser):
    await signed_in(browser, "ada@example.com")
    await register(browser, "bola@example.com")
    bola_token = (await login(browser, "bola@example.com")).json()["access_token"]
    await login(browser, "ada@example.com")  # the cookie is Ada's again

    as_bola = await browser.get(
        f"{API}/accounts/me", headers={"Authorization": f"Bearer {bola_token}"}
    )
    assert as_bola.json()["data"]["email"] == "bola@example.com"
    bad_bearer = await browser.get(
        f"{API}/accounts/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert bad_bearer.status_code == 401


async def test_signing_out_deletes_the_cookie_and_ends_its_session(browser, site):
    await signed_in(browser)
    token = browser.cookies[SESSION_COOKIE]
    response = await browser.post(f"{API}/auth/logout", headers={"Origin": site})
    assert response.status_code == 200, response.text
    header = cookie_header(response).lower()
    assert "max-age=0" in header and "secure" in header and "httponly" in header
    assert SESSION_COOKIE not in browser.cookies
    assert (await browser.get(f"{API}/accounts/me")).status_code == 401
    # the old value, sent again by hand, no longer works either
    browser.cookies.set(SESSION_COOKIE, token, domain="test")
    assert (await browser.get(f"{API}/accounts/me")).status_code == 401


async def test_signing_out_everywhere_from_another_device_ends_the_cookie_session(browser):
    await signed_in(browser)
    other_device = (await login(browser, "ada@example.com")).json()["access_token"]
    await login(browser, "ada@example.com")  # this browser's own cookie session
    cookie = browser.cookies[SESSION_COOKIE]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as device:
        response = await device.post(
            f"{API}/auth/logout",
            params={"everywhere": "true"},
            headers={"Authorization": f"Bearer {other_device}"},
        )
    assert response.status_code == 200
    assert browser.cookies[SESSION_COOKIE] == cookie  # still held by this browser...
    assert (await browser.get(f"{API}/accounts/me")).status_code == 401  # ...but ended


async def test_a_plain_http_client_never_sends_the_secure_cookie(client):
    # every other test's client talks http: signing in there must not change how it is signed in
    await register(client, "ada@example.com")
    await login(client, "ada@example.com", password=PASSWORD)
    assert (await client.get(f"{API}/accounts/me")).status_code == 401
