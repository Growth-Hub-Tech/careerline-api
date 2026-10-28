"""Day 9: the adaptive test engine (no database). A test of about 16 questions that gets
harder after a right answer and easier after a wrong one, scored as a 0-100 score, a level, a
confidence, and strengths and weaknesses per subskill. No pass or fail."""

import random

import pytest

from app.services.adaptive_engine import (
    LEVELS,
    Answer,
    EngineConfig,
    is_finished,
    next_level,
    score_attempt,
    score_to_level,
)

CONFIG = EngineConfig()


def answers(pattern, start="JUNIOR", subskills=(1, 2)):
    """Answers as the engine would serve them: each next level comes from next_level."""
    given: list[Answer] = []
    for number, correct in enumerate(pattern):
        level = next_level(given, CONFIG) if given else start
        given.append(Answer(number + 1, level, subskills[number % len(subskills)], correct))
    return given


def test_the_test_starts_at_the_start_level_and_has_16_questions():
    assert CONFIG.length == 16 and CONFIG.start_level == "JUNIOR"
    assert next_level([], CONFIG) == "JUNIOR"
    assert next_level([], EngineConfig(start_level="MID")) == "MID"
    assert not is_finished(answers([True] * 15), CONFIG)
    assert is_finished(answers([True] * 16), CONFIG)


def test_harder_after_a_right_answer_easier_after_a_wrong_one():
    given = answers([True, True, True, False, False, False, False])
    served = [a.level for a in given]
    assert served == ["JUNIOR", "MID", "ADVANCED", "ADVANCED", "MID", "JUNIOR", "BEGINNER"]
    # never above ADVANCED or below BEGINNER
    assert next_level(answers([True] * 5), CONFIG) == "ADVANCED"
    assert next_level(answers([False] * 5), CONFIG) == "BEGINNER"


def test_all_right_is_advanced_and_all_wrong_is_beginner():
    best = score_attempt(answers([True] * 16), CONFIG)
    worst = score_attempt(answers([False] * 16), CONFIG)
    assert best.level == "ADVANCED" and best.score >= 85
    assert worst.level == "BEGINNER" and worst.score <= 15
    assert 0 <= worst.confidence <= 1 and 0 <= best.confidence <= 1


def test_the_score_and_the_level_always_agree():
    rng = random.Random(7)
    for _ in range(200):
        result = score_attempt(answers([rng.random() < 0.6 for _ in range(16)]), CONFIG)
        assert 0 <= result.score <= 100
        assert result.level == score_to_level(result.score, CONFIG)


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (0, "BEGINNER"),
        (40, "BEGINNER"),
        (41, "JUNIOR"),
        (60, "JUNIOR"),
        (61, "MID"),
        (80, "MID"),
        (81, "ADVANCED"),
        (100, "ADVANCED"),
    ],
)
def test_levels_follow_the_score_bands(score, level):
    assert score_to_level(score, CONFIG) == level


def test_more_right_answers_never_lower_the_score():
    previous = -1
    for right in range(17):
        result = score_attempt(answers([True] * right + [False] * (16 - right)), CONFIG)
        assert result.score >= previous
        previous = result.score


def test_a_right_answer_on_a_harder_question_counts_for_more():
    hard = [Answer(1, "ADVANCED", 1, True), Answer(2, "ADVANCED", 1, False)]
    easy = [Answer(1, "BEGINNER", 1, True), Answer(2, "BEGINNER", 1, False)]
    assert score_attempt(hard, CONFIG).score > score_attempt(easy, CONFIG).score


def test_confidence_grows_with_consistent_answers():
    short = score_attempt(answers([True, False, True, False]), CONFIG)
    full = score_attempt(answers([True, False] * 8), CONFIG)
    assert full.confidence > short.confidence
    assert full.confidence_label in {"low", "medium", "high"}


def test_strengths_and_weaknesses_by_subskill():
    given = []
    for number in range(16):
        level = LEVELS[1 + number % 2]  # JUNIOR and MID
        subskill = 1 if number % 4 < 2 else 2
        given.append(Answer(number + 1, level, subskill, correct=subskill == 1))
    result = score_attempt(given, CONFIG)
    assert result.strengths == [1]
    assert result.weaknesses == [2]
    by_id = {s.subskill_id: s for s in result.subskills}
    assert by_id[1].answered == 8 and by_id[1].correct == 8 and by_id[1].band == "strong"
    assert by_id[2].percentage_score == 0.0 and by_id[2].band == "weak"


def test_a_subskill_with_one_answer_is_neither_strength_nor_weakness():
    given = answers([True] * 15) + [Answer(99, "ADVANCED", 7, False)]
    result = score_attempt(given, CONFIG)
    assert 7 not in result.weaknesses
    assert {s.subskill_id: s.band for s in result.subskills}[7] == "developing"


def test_there_is_no_pass_or_fail():
    result = score_attempt(answers([True] * 16), CONFIG)
    fields = set(result.__dataclass_fields__)
    assert not fields & {"passed", "status", "pass_fail"}


def test_no_answers_cannot_be_scored():
    with pytest.raises(ValueError):
        score_attempt([], CONFIG)


def test_the_same_answers_always_give_the_same_result():
    given = answers([True, False, True, True, False, True, False, True] * 2)
    assert score_attempt(given, CONFIG) == score_attempt(list(given), CONFIG)
