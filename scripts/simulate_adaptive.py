"""Simulate the adaptive test (Day 9): do the scores separate the levels?

Simulated people at each level take the real engine's test (app/services/adaptive_engine.py
with the real picking, app/services/question_picking.py) on a question bank shaped like ours:
5 subskills and 25 questions per level. Each person has a true ability inside their level
(0-1 BEGINNER, 1-2 JUNIOR, 2-3 MID, 3-4 ADVANCED, spread evenly) and answers each question
right with the model's chance. Real questions are not exactly as hard as their label says, so
each question's true difficulty is its label plus random noise (--label-noise, default 0.3 of
a level); the engine only sees the label.

Prints, per true level: the scores, how many got exactly their level, the confidence; the
whole confusion table; how far apart neighbouring levels are (d = difference of the average
scores / their pooled standard deviation; above 1 the levels are well apart); how the result
holds up with more label noise; and what pure guessing and always picking the longest option
(on the real Frontend Web Development questions) would score.

Usage:
    python scripts/simulate_adaptive.py                 # 1,000 people per level
    python scripts/simulate_adaptive.py --people 200 --seed 5 --label-noise 0.5
"""

import argparse
import math
import random
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.adaptive_engine import (  # noqa: E402
    LEVELS,
    Answer,
    EngineConfig,
    next_level,
    score_attempt,
)
from app.services.question_picking import pick_next  # noqa: E402

SUBSKILLS = 5
PER_LEVEL = 25


@dataclass(frozen=True)
class SimQuestion:
    question_id: int
    subskill_id: int
    level: str
    true_difficulty: float
    longest_is_correct: bool = False


@dataclass
class LevelStats:
    mean_score: float
    sd_score: float
    p10: float
    p50: float
    p90: float
    exact: float
    mean_confidence: float
    mean_answered: float


@dataclass
class Report:
    people_per_level: int
    label_noise: float
    level_names: tuple[str, ...] = LEVELS
    levels: dict[str, LevelStats] = field(default_factory=dict)
    confusion: dict[str, Counter] = field(default_factory=dict)
    separation: list[float] = field(default_factory=list)
    exact_accuracy: float = 0.0
    within_one_level: float = 0.0
    confidence_when_right: float = 0.0
    confidence_when_wrong: float = 0.0


def make_bank(rng: random.Random, label_noise: float) -> list[SimQuestion]:
    bank, number = [], 0
    for index, level in enumerate(LEVELS):
        for i in range(PER_LEVEL):
            number += 1
            noise = rng.gauss(0, label_noise) if label_noise else 0.0
            bank.append(SimQuestion(number, 1 + i % SUBSKILLS, level, index + noise))
    return bank


def chance(ability: float, true_difficulty: float, config: EngineConfig) -> float:
    slope = config.discrimination * (ability - true_difficulty)
    return config.guessing + (1 - config.guessing) / (1 + math.exp(-slope))


def take_test(bank, answer_fn, rng: random.Random, config: EngineConfig):
    answers: list[Answer] = []
    served: list[SimQuestion] = []
    while len(answers) < config.length:
        level = next_level(answers, config)
        question = pick_next(bank, level, served, {}, rng, level_of=lambda q: q.level)
        if question is None:
            break
        served.append(question)
        answers.append(
            Answer(question.question_id, question.level, question.subskill_id, answer_fn(question))
        )
    return score_attempt(answers, config)


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def simulate(people_per_level: int = 1000, seed: int = 1, label_noise: float = 0.3) -> Report:
    config = EngineConfig()
    rng = random.Random(seed)
    bank = make_bank(rng, label_noise)
    report = Report(people_per_level=people_per_level, label_noise=label_noise)
    scores: dict[str, list[int]] = {}
    right_conf, wrong_conf = [], []
    for index, level in enumerate(LEVELS):
        results = []
        for _ in range(people_per_level):
            ability = index + rng.random()

            def answer(question: SimQuestion, ability: float = ability) -> bool:
                return rng.random() < chance(ability, question.true_difficulty, config)

            results.append(take_test(bank, answer, rng, config))
        level_scores = [r.score for r in results]
        scores[level] = level_scores
        report.confusion[level] = Counter(r.level for r in results)
        for r in results:
            (right_conf if r.level == level else wrong_conf).append(r.confidence)
        report.levels[level] = LevelStats(
            mean_score=statistics.fmean(level_scores),
            sd_score=statistics.pstdev(level_scores),
            p10=_percentile(level_scores, 0.1),
            p50=_percentile(level_scores, 0.5),
            p90=_percentile(level_scores, 0.9),
            exact=report.confusion[level][level] / people_per_level,
            mean_confidence=statistics.fmean(r.confidence for r in results),
            mean_answered=statistics.fmean(r.answered for r in results),
        )
    total = people_per_level * len(LEVELS)
    report.exact_accuracy = sum(report.confusion[lv][lv] for lv in LEVELS) / total
    report.within_one_level = (
        sum(
            count
            for true_level, counter in report.confusion.items()
            for got, count in counter.items()
            if abs(LEVELS.index(got) - LEVELS.index(true_level)) <= 1
        )
        / total
    )
    for low, high in zip(LEVELS, LEVELS[1:], strict=False):
        pooled = math.sqrt(
            (statistics.pvariance(scores[low]) + statistics.pvariance(scores[high])) / 2
        )
        report.separation.append(
            (statistics.fmean(scores[high]) - statistics.fmean(scores[low])) / pooled
        )
    report.confidence_when_right = statistics.fmean(right_conf) if right_conf else 0.0
    report.confidence_when_wrong = statistics.fmean(wrong_conf) if wrong_conf else 0.0
    return report


def guessers(people: int, seed: int) -> list[int]:
    config, rng = EngineConfig(), random.Random(seed)
    bank = make_bank(rng, 0.0)
    return [
        take_test(bank, lambda q: rng.random() < 0.25, rng, config).score for _ in range(people)
    ]


def longest_option_pickers(people: int, seed: int, skill_id: int = 1) -> tuple[str, list[int]]:
    """Always pick the longest option, on the real ACTIVE questions of one skill."""
    from app.db.seed import read_seed_rows

    rows = read_seed_rows()
    skill_of = {s["subskill_id"]: s["skill_id"] for s in rows["subskills"]}
    name = next(s["skill_name"] for s in rows["skills"] if s["skill_id"] == skill_id)
    options: dict[int, list[dict]] = {}
    for option in rows["options"]:
        options.setdefault(option["question_id"], []).append(option)
    bank = []
    for q in rows["questions"]:
        if skill_of[q["subskill_id"]] != skill_id or q["status"].value != "ACTIVE":
            continue
        opts = options[q["question_id"]]
        longest = max(opts, key=lambda o: len(o["option_text"].strip()))
        lengths = sorted((len(o["option_text"].strip()) for o in opts), reverse=True)
        single = len(lengths) < 2 or lengths[0] > lengths[1]
        bank.append(
            SimQuestion(
                q["question_id"],
                q["subskill_id"],
                q["difficulty_level"].value,
                0.0,
                longest_is_correct=single and bool(longest["is_correct"]),
            )
        )
    config, rng = EngineConfig(), random.Random(seed)
    results = [
        take_test(bank, lambda q: q.longest_is_correct or rng.random() < 0.25, rng, config).score
        for _ in range(people)
    ]
    return name, results


def print_report(report: Report) -> None:
    print(
        f"Adaptive test simulation: people per level: {report.people_per_level}, "
        f"label noise {report.label_noise} of a level, {EngineConfig().length} questions each"
    )
    print(
        f"\n{'true level':<10} {'mean':>6} {'sd':>5} {'p10':>5} {'p50':>5} {'p90':>5} "
        f"{'exact':>6} {'confidence':>10}"
    )
    for level in LEVELS:
        s = report.levels[level]
        print(
            f"{level:<10} {s.mean_score:6.1f} {s.sd_score:5.1f} {s.p10:5.0f} {s.p50:5.0f} "
            f"{s.p90:5.0f} {100 * s.exact:5.1f}% {s.mean_confidence:10.2f}"
        )
    print("\nConfusion (rows: true level, columns: level given, % of the row):")
    print(f"{'':<10}" + "".join(f"{level:>10}" for level in LEVELS))
    for level in LEVELS:
        row = report.confusion[level]
        print(
            f"{level:<10}"
            + "".join(f"{100 * row[got] / report.people_per_level:9.1f}%" for got in LEVELS)
        )
    print(
        f"\nExact level: {100 * report.exact_accuracy:.1f}%   "
        f"within one level: {100 * report.within_one_level:.1f}%"
    )
    print(
        "Separation of neighbouring levels (d; above 1 is well apart): "
        + ", ".join(
            f"{low}-{high} {d:.2f}"
            for (low, high), d in zip(
                zip(LEVELS, LEVELS[1:], strict=False), report.separation, strict=True
            )
        )
    )
    print(
        f"Average confidence when the level is right: {report.confidence_when_right:.2f}, "
        f"when wrong: {report.confidence_when_wrong:.2f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--people", type=int, default=1000, help="simulated people per level")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--label-noise", type=float, default=0.3)
    args = ap.parse_args()

    report = simulate(args.people, args.seed, args.label_noise)
    print_report(report)

    print("\nWith more or less noise in the difficulty labels:")
    for noise in (0.0, 0.6):
        other = simulate(max(100, args.people // 4), args.seed + 1, noise)
        print(
            f"  noise {noise}: exact {100 * other.exact_accuracy:.1f}%, within one "
            f"{100 * other.within_one_level:.1f}%, d "
            + ", ".join(f"{d:.2f}" for d in other.separation)
        )

    guess = guessers(max(100, args.people // 4), args.seed)
    print(
        f"\nPure guessing: average score {statistics.fmean(guess):.1f}, "
        f"{100 * sum(s <= 40 for s in guess) / len(guess):.0f}% get BEGINNER"
    )
    name, longest = longest_option_pickers(max(100, args.people // 4), args.seed)
    levels = Counter(
        "ADVANCED" if s > 80 else "MID" if s > 60 else "JUNIOR" if s > 40 else "BEGINNER"
        for s in longest
    )
    print(
        f"Always picking the longest option ({name}, its ACTIVE questions): average score "
        f"{statistics.fmean(longest):.1f}; levels "
        + ", ".join(f"{lv} {100 * levels[lv] / len(longest):.0f}%" for lv in LEVELS)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
