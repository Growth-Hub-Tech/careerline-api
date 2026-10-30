"""Day 8: scripts/check_questions.py, the one question-quality check (it replaces
scripts/check_option_bias.py). It reads the seed files, so it needs no database."""

import csv
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_questions.py"


def run(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True
    )


def test_the_summary_covers_the_whole_bank_and_every_skill():
    result = run()
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Questions checked: 4000" in out
    assert "Correct option is the single longest" in out
    assert "Frontend Web Development" in out and "ready" in out
    assert "Skills that can be tested" in out


def test_the_review_file_for_the_experts(tmp_path):
    review = tmp_path / "review.csv"
    result = run("--review-file", str(review), "--skill", "1")
    assert result.returncode == 0, result.stderr
    rows = list(csv.DictReader(review.open(encoding="utf-8")))
    assert rows, "skill 1 has flagged questions"
    assert set(rows[0]) >= {
        "question_id",
        "skill",
        "subskill",
        "level",
        "status",
        "issues",
        "question",
        "correct_option",
        "wrong_options",
        "decision",
        "reviewer",
        "note",
    }
    assert {row["skill"] for row in rows} == {"Frontend Web Development"}
    assert all(row["issues"] for row in rows)
    assert all(row["decision"] == "" for row in rows)
    # blocked questions first, so the experts start where it matters
    statuses = [row["status"] for row in rows]
    assert statuses == sorted(statuses, key=lambda s: s != "NEEDS_REVIEW")


def test_filled_in_decisions_go_into_the_reviews_seed_file(tmp_path):
    review = tmp_path / "review.csv"
    run("--review-file", str(review), "--skill", "1")
    rows = list(csv.DictReader(review.open(encoding="utf-8")))
    rows[0]["decision"], rows[0]["reviewer"] = "approved", "Expert One"
    rows[1]["decision"], rows[1]["note"] = "rejected", "two answers are right"
    with review.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    reviews_file = tmp_path / "question_reviews.json"
    reviews_file.write_text(json.dumps({"reviews": []}), encoding="utf-8")

    result = run("--apply-reviews", str(review), "--reviews-file", str(reviews_file))
    assert result.returncode == 0, result.stderr
    saved = json.loads(reviews_file.read_text(encoding="utf-8"))["reviews"]
    assert [(r["question_id"], r["decision"]) for r in saved] == [
        (int(rows[0]["question_id"]), "approved"),
        (int(rows[1]["question_id"]), "rejected"),
    ]
    assert saved[0]["reviewer"] == "Expert One" and saved[1]["note"] == "two answers are right"


def test_a_bad_decision_is_refused(tmp_path):
    review = tmp_path / "review.csv"
    review.write_text("question_id,decision\n1,maybe\n", encoding="utf-8")
    reviews_file = tmp_path / "question_reviews.json"
    reviews_file.write_text(json.dumps({"reviews": []}), encoding="utf-8")
    result = run("--apply-reviews", str(review), "--reviews-file", str(reviews_file))
    assert result.returncode != 0
    assert "maybe" in result.stderr
    assert json.loads(reviews_file.read_text(encoding="utf-8"))["reviews"] == []


def test_the_ci_limit_on_length_bias():
    assert run("--max-share", "100").returncode == 0
    assert run("--max-share", "1").returncode == 1
