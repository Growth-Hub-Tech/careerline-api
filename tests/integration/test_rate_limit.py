"""Day 5: one database-backed rate limiter (works across restarts and server processes)."""

from app.core import rate_limit
from app.db.session import AsyncSessionLocal


async def test_the_limit_counts_inside_the_window_only(db):
    bucket = rate_limit.bucket("test", "203.0.113.7")
    async with AsyncSessionLocal() as session:
        for _ in range(3):
            assert (await rate_limit.hit(session, bucket, limit=3, window_seconds=60)).allowed
        refused = await rate_limit.hit(session, bucket, limit=3, window_seconds=60)
        assert not refused.allowed
        assert 0 < refused.retry_after <= 60
        await session.commit()

    async with AsyncSessionLocal() as session:
        # A zero-second window has nothing in it
        assert (await rate_limit.hit(session, bucket, limit=3, window_seconds=0)).allowed


async def test_buckets_are_hashed_and_separate():
    a = rate_limit.bucket("login:email", "Ada@Example.com")
    assert a == rate_limit.bucket("login:email", "ada@example.com")
    assert a != rate_limit.bucket("login:ip", "ada@example.com")
    assert "ada" not in a
