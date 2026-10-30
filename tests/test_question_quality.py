"""Day 8: the question-quality check (no database). One function decides, for every question,
what is wrong with it and whether it may be served; the seed loader and
scripts/check_questions.py both use it."""

import pytest

from app.services.question_quality import (
    Option,
    QuestionIn,
    QuestionStatus,
    Severity,
    Thresholds,
    check_bank,
    check_question,
    decide_status,
    skill_readiness,
)


def q(options, text="What does HTML stand for?", question_id=1, skill_id=1):
    return QuestionIn(
        question_id=question_id,
        skill_id=skill_id,
        text=text,
        options=tuple(Option(t, c) for t, c in options),
    )


GOOD = [
    ("Hyper Text Markup Language", True),
    ("High Tech Modern Language", False),
    ("Hyper Transfer Markup Lingo", False),
    ("Home Tool Markup Language", False),
]


def codes(issues):
    return {i.code: i.severity for i in issues}


def test_a_good_question_has_no_issues_and_is_active():
    issues = check_question(q(GOOD))
    assert issues == []
    assert decide_status(issues, None) == QuestionStatus.ACTIVE


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ([("a", True), ("b", True), ("c", False), ("d", False)], "no_single_correct"),
        ([("a", False), ("b", False), ("c", False), ("d", False)], "no_single_correct"),
        ([("yes", True), ("no", False)], "too_few_options"),
        ([("same", True), ("Same ", False), ("other", False), ("more", False)], "duplicate_option"),
        ([("a", True), ("", False), ("c", False), ("d", False)], "empty_option"),
    ],
)
def test_broken_questions_are_blocked(options, code):
    issues = check_question(q(options))
    assert codes(issues)[code] == Severity.BLOCK
    assert decide_status(issues, None) == QuestionStatus.NEEDS_REVIEW


def test_the_correct_option_giving_itself_away_by_length():
    mild = [
        ("A list of the twelve steps", True),
        ("A set of rules", False),
        ("Some odd words", False),
        ("Just a few nouns", False),
    ]
    strong = [
        ("A list of every single step in the whole process, in order", True),
        ("A set of rules", False),
        ("Some odd words", False),
        ("Just a nouns", False),
    ]
    assert codes(check_question(q(mild)))["length_giveaway"] == Severity.REVIEW
    assert codes(check_question(q(strong)))["length_giveaway"] == Severity.BLOCK
    # A longest correct option that is NOT much longer than the others is fine
    close = [("Hyper Text Markup Languages", True)] + GOOD[1:]
    assert "length_giveaway" not in codes(check_question(q(close)))


def test_the_length_limits_are_settings():
    mild = [
        ("A list of the twelve steps", True),
        ("A set of rules", False),
        ("Some odd words", False),
        ("Just a few nouns", False),
    ]
    strict = Thresholds(review_ratio=1.3, block_ratio=1.5)
    assert codes(check_question(q(mild), strict))["length_giveaway"] == Severity.BLOCK


def test_review_only_issues_keep_the_question_active():
    options = GOOD[:3] + [("None of the above", False)]
    issues = check_question(q(options))
    assert codes(issues) == {"all_none_of_the_above": Severity.REVIEW}
    assert decide_status(issues, None) == QuestionStatus.ACTIVE


def test_three_options_are_allowed_but_noted():
    issues = check_question(q(GOOD[:3]))
    assert codes(issues) == {"not_four_options": Severity.REVIEW}


def test_the_same_question_twice_in_a_skill_blocks_the_later_copy():
    first = q(GOOD, text="What is HTML?", question_id=1)
    again = q(GOOD, text="  what is html? ", question_id=2)
    other_skill = q(GOOD, text="What is HTML?", question_id=3, skill_id=2)
    issues = check_bank([again, first, other_skill])
    assert issues[1] == []
    assert codes(issues[2]) == {"duplicate_question": Severity.BLOCK}
    assert issues[3] == []


def test_an_expert_decision_wins_where_it_may():
    strong = [
        ("A list of every single step in the whole process, in order", True),
        ("A set of rules", False),
        ("Some odd words", False),
        ("Just a nouns", False),
    ]
    giveaway = check_question(q(strong))
    assert decide_status(giveaway, "approved") == QuestionStatus.ACTIVE
    assert decide_status([], "rejected") == QuestionStatus.RETIRED
    # ... but approval never makes a broken question servable
    broken = check_question(q([("a", True), ("b", True), ("c", False), ("d", False)]))
    assert decide_status(broken, "approved") == QuestionStatus.NEEDS_REVIEW


def test_unknown_decisions_are_refused():
    with pytest.raises(ValueError):
        decide_status([], "maybe")


def test_a_skill_is_ready_only_when_every_level_has_enough_active_questions():
    counts = {"BEGINNER": 15, "JUNIOR": 20, "MID": 15, "ADVANCED": 16}
    assert skill_readiness(counts, minimum=15) == (True, {})
    counts["MID"] = 9
    assert skill_readiness(counts, minimum=15) == (False, {"MID": 6})
    assert skill_readiness({"BEGINNER": 30}, minimum=15) == (
        False,
        {"JUNIOR": 15, "MID": 15, "ADVANCED": 15},
    )
