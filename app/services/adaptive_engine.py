"""The adaptive test engine (Day 9). Plain, tested arithmetic, no database and no pass or fail.

How a test runs
- About 16 questions (EngineConfig.length). The first is at the start level (JUNIOR).
- After a right answer the next question is one level harder; after a wrong one, one level
  easier (never above ADVANCED or below BEGINNER). Which question at that level is chosen by
  app/services/question_picking.py (balanced across subskills, least-seen first).

How it is scored
- Ability is a number from 0 to 4 on the level scale: 0-1 BEGINNER, 1-2 JUNIOR, 2-3 MID,
  3-4 ADVANCED. A question's difficulty is its level's lower edge (BEGINNER 0, JUNIOR 1, MID 2,
  ADVANCED 3), so a person in the middle of a level answers about 78% of that level's
  questions and about 48% of the next level's.
- The chance of a right answer is the standard 3-parameter logistic curve:
      p = guessing + (1 - guessing) / (1 + exp(-discrimination * (ability - difficulty)))
  with guessing 0.25 (4 options) and discrimination 1.7.
- We start with every ability from 0 to 4 equally likely (a grid of 81 points), multiply in
  each answer's chance, and take the average of what is left: that is the ability estimate.
  A right answer on a hard question moves it up more than one on an easy question.
- score: the ability turned into 0-100 so that each level lands in its score band from
  seeds/level_thresholds.json (BEGINNER 0-40, JUNIOR 41-60, MID 61-80, ADVANCED 81-100).
- level: the band the score falls in. confidence: how much of the estimate falls inside that
  level (0 to 1; low under 0.6, high from 0.8).
- strengths and weaknesses: per subskill with at least 2 answers, the share answered right
  minus the share expected at the person's ability. 0.2 or more above is a strength, 0.2 or
  more below is a weakness.

The difficulty of each question is its author's label, not yet measured from real answers.
The simulation (scripts/simulate_adaptive.py, docs/adaptive-engine.md) shows the scores
separate the levels when the labels are right.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

LEVELS = ("BEGINNER", "JUNIOR", "MID", "ADVANCED")
GRID = tuple(i / 20 for i in range(81))  # abilities 0.00, 0.05, ... 4.00


@dataclass(frozen=True)
class Answer:
    question_id: int
    level: str  # the question's difficulty level
    subskill_id: int
    correct: bool


@dataclass(frozen=True)
class EngineConfig:
    length: int = 16
    start_level: str = "JUNIOR"
    discrimination: float = 1.7
    guessing: float = 0.25
    # score bands per level, as in seeds/level_thresholds.json
    bands: tuple[tuple[int, int], ...] = ((0, 40), (41, 60), (61, 80), (81, 100))
    strength_margin: float = 0.2
    min_answers_per_subskill: int = 2


@dataclass(frozen=True)
class SubskillResult:
    subskill_id: int
    answered: int
    correct: int
    percentage_score: float
    expected_percentage: float
    band: str  # strong | developing | weak


@dataclass(frozen=True)
class Result:
    score: int  # 0-100
    level: str
    ability: float  # 0-4
    confidence: float  # 0-1
    confidence_label: str  # low | medium | high
    answered: int
    correct: int
    strengths: list[int] = field(default_factory=list)  # subskill ids, strongest first
    weaknesses: list[int] = field(default_factory=list)  # subskill ids, weakest first
    subskills: list[SubskillResult] = field(default_factory=list)


def difficulty(level: str) -> float:
    return float(LEVELS.index(level))


def chance_right(ability: float, level: str, config: EngineConfig) -> float:
    slope = config.discrimination * (ability - difficulty(level))
    return config.guessing + (1 - config.guessing) / (1 + math.exp(-slope))


def next_level(answers: Sequence[Answer], config: EngineConfig) -> str:
    """The level of the next question: the start level first, then one up after a right
    answer and one down after a wrong one."""
    if not answers:
        return config.start_level
    last = answers[-1]
    index = LEVELS.index(last.level) + (1 if last.correct else -1)
    return LEVELS[max(0, min(len(LEVELS) - 1, index))]


def is_finished(answers: Sequence[Answer], config: EngineConfig) -> bool:
    return len(answers) >= config.length


def _posterior(answers: Sequence[Answer], config: EngineConfig) -> list[float]:
    logs = [0.0] * len(GRID)
    for answer in answers:
        for i, ability in enumerate(GRID):
            p = chance_right(ability, answer.level, config)
            logs[i] += math.log(p if answer.correct else 1 - p)
    top = max(logs)
    weights = [math.exp(value - top) for value in logs]
    total = sum(weights)
    return [w / total for w in weights]


def ability_to_score(ability: float, config: EngineConfig) -> int:
    band = min(int(ability), len(LEVELS) - 1)
    low, high = config.bands[band]
    fraction = min(1.0, ability - band)
    return min(high, low + int(fraction * (high - low + 1)))


def score_to_level(score: int, config: EngineConfig) -> str:
    for level, (low, high) in zip(LEVELS, config.bands, strict=True):
        if low <= score <= high:
            return level
    raise ValueError(f"score {score} is outside the bands")


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _subskills(
    answers: Sequence[Answer], ability: float, config: EngineConfig
) -> list[SubskillResult]:
    grouped: dict[int, list[Answer]] = {}
    for answer in answers:
        grouped.setdefault(answer.subskill_id, []).append(answer)
    results = []
    for subskill_id, items in grouped.items():
        right = sum(a.correct for a in items)
        observed = right / len(items)
        expected = sum(chance_right(ability, a.level, config) for a in items) / len(items)
        band = "developing"
        if len(items) >= config.min_answers_per_subskill:
            if observed - expected >= config.strength_margin:
                band = "strong"
            elif expected - observed >= config.strength_margin:
                band = "weak"
        results.append(
            SubskillResult(
                subskill_id=subskill_id,
                answered=len(items),
                correct=right,
                percentage_score=round(100 * observed, 2),
                expected_percentage=round(100 * expected, 2),
                band=band,
            )
        )
    return sorted(results, key=lambda s: s.subskill_id)


def score_attempt(answers: Sequence[Answer], config: EngineConfig) -> Result:
    """Score, level, confidence, strengths and weaknesses from the answers given so far."""
    if not answers:
        raise ValueError("there are no answers to score")
    posterior = _posterior(answers, config)
    ability = sum(a * w for a, w in zip(GRID, posterior, strict=True))
    score = ability_to_score(ability, config)
    level = score_to_level(score, config)
    index = LEVELS.index(level)
    low_edge, high_edge = index, index + 1
    confidence = sum(
        w
        for a, w in zip(GRID, posterior, strict=True)
        if low_edge <= a < high_edge or (index == len(LEVELS) - 1 and a == high_edge)
    )
    subskills = _subskills(answers, ability, config)

    def gap(s: SubskillResult) -> float:
        return s.percentage_score - s.expected_percentage

    return Result(
        score=score,
        level=level,
        ability=round(ability, 3),
        confidence=round(confidence, 3),
        confidence_label=_confidence_label(confidence),
        answered=len(answers),
        correct=sum(a.correct for a in answers),
        strengths=[
            s.subskill_id for s in sorted(subskills, key=gap, reverse=True) if s.band == "strong"
        ],
        weaknesses=[s.subskill_id for s in sorted(subskills, key=gap) if s.band == "weak"],
        subskills=subskills,
    )
