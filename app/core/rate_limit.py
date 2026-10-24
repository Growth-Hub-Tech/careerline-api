"""One rate limiter, stored in Postgres (rate_limit_events), so limits hold across restarts and
across server processes.

    result = await rate_limit.hit(db, rate_limit.bucket("contact:ip", ip), limit=5, window_seconds=3600)
    if not result.allowed:
        raise RateLimitedError(..., headers={"Retry-After": str(result.retry_after)})

A bucket is "<kind>:<keyed hash>": the email or IP address itself is never stored.
"""

import hashlib
import hmac
import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

# Events older than this are deleted as new ones come in (no limit looks back further)
KEEP_SECONDS = 24 * 3600


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int = 0  # seconds until the next action would be allowed


def bucket(kind: str, value: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode(), value.strip().lower().encode(), hashlib.sha256
    ).hexdigest()
    return f"{kind}:{digest[:40]}"


async def count(db: AsyncSession, bucket_key: str, window_seconds: float) -> tuple[int, float]:
    """How many events are in the window, and how many seconds until the oldest leaves it."""
    row = (
        await db.execute(
            text(
                "SELECT count(*) AS n,"
                " COALESCE(EXTRACT(EPOCH FROM (min(created_at) + make_interval(secs => :window)"
                " - now())), 0) AS wait "
                "FROM rate_limit_events "
                "WHERE bucket = :bucket AND created_at > now() - make_interval(secs => :window)"
            ),
            {"bucket": bucket_key, "window": float(window_seconds)},
        )
    ).one()
    return int(row.n), float(row.wait)


async def record(db: AsyncSession, bucket_key: str) -> None:
    await db.execute(
        text("INSERT INTO rate_limit_events (bucket) VALUES (:bucket)"), {"bucket": bucket_key}
    )
    # Housekeeping: drop a few expired events each time (keeps the table small)
    await db.execute(
        text(
            "DELETE FROM rate_limit_events WHERE id IN (SELECT id FROM rate_limit_events "
            "WHERE created_at < now() - make_interval(secs => :keep) LIMIT 100)"
        ),
        {"keep": float(KEEP_SECONDS)},
    )


async def clear(db: AsyncSession, bucket_key: str) -> None:
    await db.execute(text("DELETE FROM rate_limit_events WHERE bucket = :b"), {"b": bucket_key})


async def hit(
    db: AsyncSession, bucket_key: str, *, limit: int, window_seconds: float
) -> RateLimitResult:
    """Count one action if the bucket is under its limit; refuse it otherwise."""
    # One request at a time per bucket, so two parallel requests can't both take the last slot
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:b))"), {"b": bucket_key})
    used, wait = await count(db, bucket_key, window_seconds)
    if used >= limit:
        return RateLimitResult(allowed=False, retry_after=max(1, math.ceil(wait)))
    await record(db, bucket_key)
    return RateLimitResult(allowed=True)
