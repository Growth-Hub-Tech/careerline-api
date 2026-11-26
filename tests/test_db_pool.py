"""The database pool is bounded per process: every web worker and the job worker open at most
DB_POOL_SIZE + DB_MAX_OVERFLOW connections (SQLAlchemy reads a pool size of 0 as "no limit")."""

from app.db import session


def test_the_engine_pool_is_five_plus_five():
    assert (session.DB_POOL_SIZE, session.DB_MAX_OVERFLOW) == (5, 5)
    assert session.engine.pool.size() == 5
    assert session.engine.pool._max_overflow == 5  # type: ignore[attr-defined]
