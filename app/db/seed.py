"""Load the reference data in seeds/ into the database: `python -m app.db.seed`.

Reference data = proficiency levels, level thresholds, skills, subskills, questions with their
options, and behavioural questions. Each row keeps its id from the seed file and is upserted on
it, so loading twice is safe: the second load changes nothing, and a row someone edited in the
database is put back to what the seed file says. Rows that are not in the files are left alone
(attempts may point at them), and learners' data is never touched. Afterwards the id counters
are moved past the highest id, so rows the app creates later get fresh ids.

The seed files are the source of truth for the question bank: change a question there, in a pull
request, and load again.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Table, create_engine, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.pool import NullPool

from app.models.models import (
    BehaviouralQuestion,
    LevelName,
    LevelThreshold,
    Option,
    ProficiencyLevel,
    Question,
    QuestionType,
    Skill,
    Subskill,
)

SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"
BATCH = 1000

# Load order follows the foreign keys
TABLES: dict[str, Table] = {
    "proficiency_level": ProficiencyLevel.__table__,  # type: ignore[dict-item]
    "level_threshold": LevelThreshold.__table__,  # type: ignore[dict-item]
    "skills": Skill.__table__,  # type: ignore[dict-item]
    "subskills": Subskill.__table__,  # type: ignore[dict-item]
    "questions": Question.__table__,  # type: ignore[dict-item]
    "options": Option.__table__,  # type: ignore[dict-item]
    "behavioural_questions": BehaviouralQuestion.__table__,  # type: ignore[dict-item]
}
LEVEL_TABLES = ("proficiency_level", "level_threshold")


@dataclass
class Counts:
    in_files: int = 0
    inserted: int = 0
    updated: int = 0

    @property
    def unchanged(self) -> int:
        return self.in_files - self.inserted - self.updated


def _read(name: str) -> Any:
    return json.loads((SEEDS_DIR / name).read_text(encoding="utf-8"))


def read_seed_rows() -> dict[str, list[dict[str, Any]]]:
    """Every seed row, by table, with the database's column names."""
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
    rows["proficiency_level"] = [
        {**level, "level_name": LevelName(level["level_name"])}
        for level in _read("proficiency_levels.json")
    ]
    rows["level_threshold"] = _read("level_thresholds.json")
    for skill in _read("skills.json"):
        subskills = skill.pop("subskills")
        rows["skills"].append(skill)
        rows["subskills"].extend({**s, "skill_id": skill["skill_id"]} for s in subskills)
    for path in sorted((SEEDS_DIR / "questions").glob("*.json")):
        for question in json.loads(path.read_text(encoding="utf-8"))["questions"]:
            options = question.pop("options")
            rows["questions"].append(
                {**question, "difficulty_level": LevelName(question["difficulty_level"])}
            )
            rows["options"].extend({**o, "question_id": question["question_id"]} for o in options)
    rows["behavioural_questions"] = [
        {**q, "question_type": QuestionType(q["question_type"])}
        for q in _read("behavioural_questions.json")
    ]
    return rows


def _upsert(conn: Connection, table: Table, rows: list[dict[str, Any]]) -> Counts:
    counts = Counts(in_files=len(rows))
    (key,) = table.primary_key.columns
    for start in range(0, len(rows), BATCH):
        values = insert(table).values(rows[start : start + BATCH])
        columns = [c for c in rows[0] if c != key.name]
        upsert: Any = values.on_conflict_do_update(
            index_elements=[key],
            set_={c: values.excluded[c] for c in columns},
            # only rows that really differ count as updated
            where=or_(*(table.c[c].is_distinct_from(values.excluded[c]) for c in columns)),
        ).returning(literal_column("xmax = 0").label("inserted"))
        for (inserted,) in conn.execute(upsert):
            if inserted:
                counts.inserted += 1
            else:
                counts.updated += 1
    return counts


def _move_id_counter_past_max(conn: Connection, table: Table) -> None:
    (key,) = table.primary_key.columns
    highest = conn.execute(select(func.max(key))).scalar()
    conn.execute(
        text("SELECT setval(pg_get_serial_sequence(:table, :column), :value, :called)"),
        {
            "table": table.name,
            "column": key.name,
            "value": highest or 1,
            "called": highest is not None,
        },
    )


def load(conn: Connection, tables: tuple[str, ...] = tuple(TABLES)) -> dict[str, Counts]:
    """Upsert the seed rows of these tables (all by default) inside the caller's transaction."""
    rows = read_seed_rows()
    result: dict[str, Counts] = {}
    for name, table in TABLES.items():
        if name not in tables:
            continue
        result[name] = _upsert(conn, table, rows[name]) if rows[name] else Counts()
        _move_id_counter_past_max(conn, table)
    return result


def main() -> int:
    from app.core.config import settings

    engine = create_engine(settings.sync_database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            result = load(conn)
    finally:
        engine.dispose()
    width = max(len(name) for name in result)
    print(f"{'table'.ljust(width)}  in files  inserted  updated  unchanged")
    for name, c in result.items():
        print(
            f"{name.ljust(width)}  {c.in_files:8}  {c.inserted:8}  {c.updated:7}  {c.unchanged:9}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
