"""Day 9: simulated people at every level get scores that separate the levels
(scripts/simulate_adaptive.py; the full run of 1,000 people per level is in
docs/adaptive-engine.md)."""

import subprocess
import sys
from pathlib import Path

from scripts.simulate_adaptive import simulate

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_scores_separate_the_levels():
    report = simulate(people_per_level=150, seed=11)
    means = [report.levels[level].mean_score for level in report.level_names]
    assert means == sorted(means), "a higher true level always has a higher average score"
    for gap in report.separation:
        assert gap > 1.0, f"neighbouring levels overlap too much (d = {gap:.2f})"
    assert report.exact_accuracy >= 0.6
    assert report.within_one_level >= 0.97
    assert all(stats.mean_answered == 16 for stats in report.levels.values())


def test_confidence_means_something():
    report = simulate(people_per_level=150, seed=12)
    assert report.confidence_when_right > report.confidence_when_wrong


def test_the_command_line_summary():
    run = subprocess.run(
        [sys.executable, "scripts/simulate_adaptive.py", "--people", "40", "--seed", "3"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "people per level: 40" in run.stdout
    assert "Exact level" in run.stdout and "Separation" in run.stdout
