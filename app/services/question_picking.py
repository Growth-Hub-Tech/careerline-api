"""Picking questions (Day 9): balanced across subskills, the questions a person has seen least
first, one question at a time for the adaptive test (pick_next). (pick_balanced, the picking of
the fixed test, went with that test on Day 10.) Works on any objects with question_id and
subskill_id (ORM rows or the simulation's questions); no database.
"""

import random
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any, Protocol

LEVELS = ("BEGINNER", "JUNIOR", "MID", "ADVANCED")


class Pickable(Protocol):
    @property
    def question_id(self) -> int: ...

    @property
    def subskill_id(self) -> int: ...


def _least_seen_groups[T: Pickable](
    pool: Sequence[T], seen: dict[int, int], rng: random.Random
) -> dict[int, list[T]]:
    """Questions grouped by subskill; inside each group the least seen first, random among
    equals."""
    groups: dict[int, list[T]] = {}
    for question in pool:
        groups.setdefault(question.subskill_id, []).append(question)
    for questions in groups.values():
        questions.sort(key=lambda q: (seen.get(q.question_id, 0), rng.random()))
    return groups


def pick_next[T: Pickable](
    pool: Sequence[T],
    level: str,
    served: Sequence[Any],
    seen: dict[int, int],
    rng: random.Random,
    level_of: Callable[[T], str],
) -> T | None:
    """The next question of an adaptive test: at `level` (or the nearest level that still has
    one), not served in this attempt yet, from the subskill served least so far, the least
    seen by this person. None when the pool is used up."""
    served_ids = {q.question_id for q in served}
    used = Counter(q.subskill_id for q in served)
    by_distance = sorted(
        LEVELS,
        key=lambda other: (abs(LEVELS.index(other) - LEVELS.index(level)), LEVELS.index(other)),
    )
    for candidate_level in by_distance:
        candidates = [
            q for q in pool if level_of(q) == candidate_level and q.question_id not in served_ids
        ]
        if not candidates:
            continue
        groups = _least_seen_groups(candidates, seen, rng)
        fewest = min(used.get(subskill_id, 0) for subskill_id in groups)
        subskills = sorted(s for s in groups if used.get(s, 0) == fewest)
        subskill_id = rng.choice(subskills)
        return groups[subskill_id][0]
    return None
