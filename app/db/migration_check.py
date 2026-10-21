from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


class MigrationsPendingError(RuntimeError):
    pass


#Revision(s) the code expects: the head(s) of migrations/versions
def expected_heads() -> set[str]:
    return set(ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_heads())


#Revision(s) the database is at, from its alembic_version table
async def current_revisions(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        heads = await conn.run_sync(lambda sync_conn: MigrationContext.configure(sync_conn).get_current_heads())
    return set(heads)


#Raises when the database is not exactly at the latest migration, so the app never serves an old schema
async def assert_database_at_head(engine: AsyncEngine) -> None:
    expected = expected_heads()
    current = await current_revisions(engine)
    if current != expected:
        raise MigrationsPendingError(
            f"Database is at {sorted(current) or 'no revision'} but the code expects {sorted(expected)}. "
            "Run `alembic upgrade head` (scripts/start.sh does this before starting the server)."
        )
