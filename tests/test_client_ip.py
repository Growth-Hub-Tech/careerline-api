"""Per-IP limits use the address Render's proxy appends (the last X-Forwarded-For hop)."""

from starlette.requests import Request

from app.core.rate_limit import client_ip


def _request(*forwarded_for: str, client: tuple[str, int] | None = ("10.0.0.9", 5000)) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded_for]
    return Request({"type": "http", "headers": headers, "client": client})


def test_the_last_hop_is_the_address_the_proxy_saw():
    assert client_ip(_request("203.0.113.7")) == "203.0.113.7"
    assert client_ip(_request("1.2.3.4, 5.6.7.8 , 203.0.113.7")) == "203.0.113.7"


def test_a_second_header_line_from_the_client_cannot_hide_the_proxy_hop():
    # the proxy's value is still the last hop when the client sent its own header line first
    assert client_ip(_request("1.2.3.4", "198.51.100.2, 203.0.113.7")) == "203.0.113.7"


def test_without_a_usable_header_the_connection_address_is_used():
    assert client_ip(_request()) == "10.0.0.9"
    assert client_ip(_request("1.2.3.4, ")) == "10.0.0.9"
    assert client_ip(_request("")) == "10.0.0.9"


def test_no_header_and_no_connection_address_is_none():
    assert client_ip(_request(client=None)) is None
