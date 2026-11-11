"""The database pool is bounded per process (Render's small Postgres has few connections)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.db.session import engine


def _settings(**values) -> Settings:
    return Settings(_env_file=None, DATABASE_URL="postgresql://x/y", SECRET_KEY="k", **values)


def test_the_pool_defaults_to_five_plus_five():
    defaults = _settings()
    assert (defaults.DB_POOL_SIZE, defaults.DB_MAX_OVERFLOW) == (5, 5)


def test_the_engine_uses_the_pool_settings():
    assert engine.pool.size() == settings.DB_POOL_SIZE
    assert engine.pool._max_overflow == settings.DB_MAX_OVERFLOW  # type: ignore[attr-defined]


@pytest.mark.parametrize("values", [{"DB_POOL_SIZE": 0}, {"DB_MAX_OVERFLOW": -1}])
def test_an_unbounded_or_negative_pool_is_refused(values):
    # SQLAlchemy reads pool_size=0 as "no limit"
    with pytest.raises(ValidationError):
        _settings(**values)
