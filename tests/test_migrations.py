"""Migrations: one clean starting migration (Day 4), then one straight line of changes on top."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
# The head of the old hand-built chain: the Render test database's alembic_version said this
# on Day 4, so it must stay the starting migration (the test database is already there).
OLD_HEAD = "b7d24e6f0c13"


def _scripts() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_there_is_one_starting_migration_and_it_is_the_old_head():
    bases = _scripts().get_bases()
    assert bases == [OLD_HEAD]
    assert _scripts().get_revision(OLD_HEAD).down_revision is None


def test_the_migrations_form_one_straight_line():
    scripts = _scripts()
    assert len(scripts.get_heads()) == 1
    for revision in scripts.walk_revisions():
        # No merge migrations and no branches: every migration has at most one parent
        assert not isinstance(revision.down_revision, tuple | list), revision.revision
