"""Safety check for the database the integration tests use.

The integration tests delete every row between tests, so they must never point at a real
database. They only run when TEST_DATABASE_URL is set, and that URL has to look like a
local throwaway test database. Anything else stops the test run before it connects.
"""

from urllib.parse import urlsplit

# Hosts that can only be a database on this machine, in CI, or in a local Docker container
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", "postgres", "db"}


class UnsafeTestDatabase(Exception):
    pass


def check_test_database_url(url: str, *, real_database_url: str | None = None) -> None:
    """Raise UnsafeTestDatabase unless url is clearly a local test database."""
    parts = urlsplit(url)

    if not parts.scheme.startswith(("postgres", "postgresql")):
        raise UnsafeTestDatabase("TEST_DATABASE_URL must be a PostgreSQL URL")

    host = (parts.hostname or "").lower()
    if "render.com" in host:
        raise UnsafeTestDatabase("TEST_DATABASE_URL points at Render, never run tests there")
    if host not in LOCAL_HOSTS:
        raise UnsafeTestDatabase(
            f"TEST_DATABASE_URL host {host!r} is not local (allowed: {sorted(LOCAL_HOSTS)})"
        )

    database = parts.path.lstrip("/")
    if "test" not in database.lower():
        raise UnsafeTestDatabase(
            f"TEST_DATABASE_URL database {database!r} must have 'test' in its name"
        )

    if real_database_url and _same_database(url, real_database_url):
        raise UnsafeTestDatabase("TEST_DATABASE_URL is the same database as DATABASE_URL in .env")


def _same_database(a: str, b: str) -> bool:
    pa, pb = urlsplit(a), urlsplit(b)
    return (pa.hostname, pa.port or 5432, pa.path) == (pb.hostname, pb.port or 5432, pb.path)
