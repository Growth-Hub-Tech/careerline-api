"""The migration on a real Postgres: it creates exactly what the models describe, and it can be
undone and redone."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text

from app.models.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_migrated_database_matches_the_models(database):
    with database.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_migration_can_be_undone_and_redone(database):
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    try:
        command.downgrade(config, "base")
        with database.connect() as conn:
            tables = conn.execute(
                text(
                    "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            ).scalar_one()
            enum_types = conn.execute(
                text("SELECT count(*) FROM pg_type WHERE typtype = 'e'")
            ).scalar_one()
        assert (tables, enum_types) == (0, 0)
    finally:
        command.upgrade(config, "head")
