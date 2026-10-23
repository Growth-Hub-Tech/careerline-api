"""One clean starting migration (Day 4) that already-migrated databases accept as their head."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
# The head of the old hand-built chain: the Render test database's alembic_version says this
OLD_HEAD = "b7d24e6f0c13"


def _scripts() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return ScriptDirectory.from_config(config)


def test_there_is_one_starting_migration():
    revisions = list(_scripts().walk_revisions())
    assert len(revisions) == 1, [r.revision for r in revisions]
    assert revisions[0].down_revision is None


def test_a_database_migrated_by_the_old_chain_is_already_at_head():
    assert _scripts().get_heads() == [OLD_HEAD]
