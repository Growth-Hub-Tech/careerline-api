"""The seed files themselves (no database): complete, consistent, and free of personal data."""

import re

import pytest

from app.db.seed import SEEDS_DIR, read_question_reviews, read_seed_rows

ROWS = read_seed_rows()
LEVELS = {"BEGINNER", "JUNIOR", "MID", "ADVANCED"}
LEVEL_ORDER = ["BEGINNER", "JUNIOR", "MID", "ADVANCED"]


def _ids(table: str, key: str) -> list[int]:
    return [row[key] for row in ROWS[table]]


def test_the_four_proficiency_levels_and_their_score_bands():
    assert {str(r["level_name"].value) for r in ROWS["proficiency_level"]} == LEVELS
    bands = sorted((r["min_score"], r["max_score"]) for r in ROWS["level_threshold"])
    assert bands[0][0] == 0 and bands[-1][1] == 100
    for (_, high), (low, _) in zip(bands, bands[1:], strict=False):
        assert low == high + 1, "score bands must not overlap or leave gaps"


def test_the_question_bank_is_all_there():
    assert len(ROWS["skills"]) == 50
    assert len(ROWS["subskills"]) == 221
    assert len(ROWS["questions"]) == 4000
    assert len(ROWS["options"]) == 16000
    assert len(ROWS["behavioural_questions"]) == 10


@pytest.mark.parametrize(
    "table,key",
    [
        ("proficiency_level", "level_id"),
        ("level_threshold", "threshold_id"),
        ("skills", "skill_id"),
        ("subskills", "subskill_id"),
        ("questions", "question_id"),
        ("options", "option_id"),
        ("behavioural_questions", "question_id"),
    ],
)
def test_ids_are_unique(table, key):
    ids = _ids(table, key)
    assert len(ids) == len(set(ids))


def test_every_reference_points_at_a_row_that_exists():
    skills, subskills = set(_ids("skills", "skill_id")), set(_ids("subskills", "subskill_id"))
    questions, levels = (
        set(_ids("questions", "question_id")),
        set(_ids("proficiency_level", "level_id")),
    )
    assert {r["skill_id"] for r in ROWS["subskills"]} <= skills
    assert {r["subskill_id"] for r in ROWS["questions"]} <= subskills
    assert {r["question_id"] for r in ROWS["options"]} <= questions
    assert {r["level_id"] for r in ROWS["level_threshold"]} <= levels
    assert {r["skill_id"] for r in ROWS["behavioural_questions"]} - {None} <= skills


def test_every_question_has_options_and_exactly_one_right_answer():
    options: dict[int, list[bool]] = {}
    for option in ROWS["options"]:
        options.setdefault(option["question_id"], []).append(option["is_correct"])
    for question in ROWS["questions"]:
        answers = options[question["question_id"]]
        assert len(answers) >= 2, question["question_id"]
        assert answers.count(True) == 1, question["question_id"]
        assert str(question["difficulty_level"].value) in LEVELS


def test_every_level_has_questions_for_every_skill_with_questions():
    by_skill: dict[int, set[str]] = {}
    subskill_skill = {r["subskill_id"]: r["skill_id"] for r in ROWS["subskills"]}
    for question in ROWS["questions"]:
        by_skill.setdefault(subskill_skill[question["subskill_id"]], set()).add(
            str(question["difficulty_level"].value)
        )
    assert all(levels == LEVELS for levels in by_skill.values())


def test_the_eight_pilot_job_roles_use_skills_that_have_questions():
    skills_with_questions = {
        row["skill_id"] for row in ROWS["subskills"] if row["subskill_id"] in _question_subskills()
    }
    roles = ROWS["job_roles"]
    assert len(roles) == 8
    assert len({r["slug"] for r in roles}) == 8
    assert {r["track"] for r in roles} <= {"tech", "revenue"}
    by_role: dict[int, list[dict]] = {}
    for row in ROWS["job_role_skills"]:
        by_role.setdefault(row["role_id"], []).append(row)
        assert row["skill_id"] in skills_with_questions, row
        assert str(row["target_level"].value) in LEVELS
    assert set(by_role) == {r["role_id"] for r in roles}
    for rows in by_role.values():
        assert 2 <= len(rows) <= 5
        assert len({r["skill_id"] for r in rows}) == len(rows)
        # the first skill is the role's main one: the highest target level
        assert rows[0]["target_level"] == max(
            (r["target_level"] for r in rows), key=lambda level: LEVEL_ORDER.index(level.value)
        )


def test_the_job_title_ladder():
    ladder = sorted(ROWS["job_titles"], key=lambda row: row["rank"])
    assert [row["slug"] for row in ladder] == ["intern", "junior", "mid", "senior", "lead"]
    expected = [LEVEL_ORDER.index(row["expected_level"].value) for row in ladder]
    assert expected == sorted(expected), "a higher title never expects a lower level"
    assert ladder[0]["expected_level"].value == "BEGINNER"
    assert ladder[-1]["expected_level"].value == "ADVANCED"


def test_expert_decisions_point_at_real_questions():
    from app.services.question_quality import DECISIONS

    questions = set(_ids("questions", "question_id"))
    reviews = read_question_reviews()
    for question_id, decision in reviews.items():
        assert question_id in questions
        assert decision in DECISIONS


def test_every_question_has_a_status_from_the_quality_check():
    from app.services.question_quality import ISSUE_TEXT

    statuses = {str(row["status"].value) for row in ROWS["questions"]}
    assert statuses <= {"ACTIVE", "NEEDS_REVIEW", "RETIRED"}
    assert "ACTIVE" in statuses
    for row in ROWS["questions"]:
        assert set(row["quality_issues"]) <= set(ISSUE_TEXT), row["question_id"]
        if not row["quality_issues"]:
            assert row["status"].value == "ACTIVE" or row["question_id"] in read_question_reviews()


def _question_subskills() -> set[int]:
    return {row["subskill_id"] for row in ROWS["questions"]}


def test_the_seed_files_hold_no_personal_data():
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    phone = re.compile(r"(\+?234|\b0)[789]\d{9}\b")
    for path in SEEDS_DIR.rglob("*.json"):
        content = path.read_text(encoding="utf-8")
        assert not email.search(content), f"{path.name} contains an email address"
        assert not phone.search(content), f"{path.name} contains a phone number"
    names = {p.stem for p in SEEDS_DIR.glob("*.json")}
    assert not names & {"learner", "learners", "test_attempt", "learner_answer", "learner_profile"}
