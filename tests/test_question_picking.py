"""Day 9: picking questions, shared by the fixed test and the adaptive engine: balanced across
subskills, the least-seen questions first (no database)."""

import random
from dataclasses import dataclass

from app.services.question_picking import pick_balanced, pick_next


@dataclass(frozen=True)
class Q:
    question_id: int
    subskill_id: int
    level: str


def bank():
    questions, number = [], 0
    for level in ("BEGINNER", "JUNIOR", "MID", "ADVANCED"):
        for subskill in (1, 2, 3):
            for _ in range(4):
                number += 1
                questions.append(Q(number, subskill, level))
    return questions


def level_of(q: Q) -> str:
    return q.level


def test_balanced_pick_covers_every_subskill_evenly():
    pool = [q for q in bank() if q.level == "JUNIOR"]
    picked = pick_balanced(pool, seen={}, rng=random.Random(1), count=6)
    assert len(picked) == 6
    assert sorted(q.subskill_id for q in picked) == [1, 1, 2, 2, 3, 3]


def test_balanced_pick_prefers_questions_seen_least():
    pool = [q for q in bank() if q.level == "JUNIOR"]
    # 3 of the 4 questions of each subskill seen before: one never-seen question per subskill
    seen = {q.question_id: 1 for q in pool if q.question_id % 4 != 0}
    picked = pick_balanced(pool, seen=seen, rng=random.Random(2), count=3)
    assert all(q.question_id not in seen for q in picked)


def test_the_next_question_is_at_the_asked_level_and_never_repeats():
    pool, rng, served = bank(), random.Random(3), []
    for _ in range(12):
        question = pick_next(pool, "MID", served, seen={}, rng=rng, level_of=level_of)
        assert question is not None and question.level == "MID"
        assert question not in served
        served.append(question)


def test_the_next_question_goes_to_the_subskill_used_least_so_far():
    pool, rng = bank(), random.Random(4)
    served = [q for q in pool if q.level == "MID" and q.subskill_id in (1, 2)][:2]
    question = pick_next(pool, "MID", served, seen={}, rng=rng, level_of=level_of)
    assert question.subskill_id == 3


def test_the_next_question_prefers_what_the_person_has_seen_least():
    pool = bank()
    mid = [q for q in pool if q.level == "MID"]
    seen = {q.question_id: 2 for q in mid if q.question_id != mid[5].question_id}
    question = pick_next(pool, "MID", [], seen=seen, rng=random.Random(5), level_of=level_of)
    assert question == mid[5]


def test_an_empty_level_falls_back_to_the_nearest_level():
    pool = [q for q in bank() if q.level != "ADVANCED"]
    question = pick_next(pool, "ADVANCED", [], seen={}, rng=random.Random(6), level_of=level_of)
    assert question.level == "MID"
    assert pick_next([], "MID", [], seen={}, rng=random.Random(6), level_of=level_of) is None
