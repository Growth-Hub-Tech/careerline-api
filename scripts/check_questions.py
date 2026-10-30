"""The question-quality check for the whole bank (Day 8; it replaces check_option_bias.py).

Reads the seed files (no database needed) and runs app/services/question_quality.py on every
question, the same check the seed loader uses to give each question its status:

- ACTIVE: served in tests (it may still have review notes for the experts)
- NEEDS_REVIEW: has a blocking issue (e.g. not exactly one correct option, or the correct
  option is by far the longest so it gives itself away); not served until fixed or approved
- RETIRED: an expert rejected it; never served

It also shows the old option-bias numbers (how often the correct option is the single
longest; about 25% is unbiased for 4 options) and which skills can be tested: every level
needs at least MIN_ACTIVE_QUESTIONS_PER_LEVEL (15) active questions.

Usage:
    python scripts/check_questions.py                              # summary
    python scripts/check_questions.py --review-file review.csv     # + the experts' review file
    python scripts/check_questions.py --review-file r.csv --skill 1 --skill 20
    python scripts/check_questions.py --apply-reviews review.csv   # filled-in decisions ->
                                                                   #   seeds/question_reviews.json
    python scripts/check_questions.py --max-share 35               # exit 1 if the longest option
                                                                   #   is correct in > 35% (CI)

The review file lists every question with an issue, blocked ones first. Experts fill in
decision (approved or rejected), reviewer and note; --apply-reviews saves those decisions, and
the next seed load uses them. Better still, fix the question in seeds/questions/ (for length
bias, rewrite the wrong options: scripts/rebalance_distractors.py drafts that).
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.db.seed import SEEDS_DIR, read_seed_rows  # noqa: E402
from app.services import question_quality as quality  # noqa: E402

REVIEW_FIELDS = [
    "question_id",
    "skill_id",
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
]
DEFAULT_MINIMUM = 15


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--review-file", help="write the questions with issues to this CSV file")
    ap.add_argument("--skill", type=int, action="append", help="only this skill id (repeatable)")
    ap.add_argument("--apply-reviews", help="save the decisions filled in this review file")
    ap.add_argument(
        "--reviews-file",
        default=str(SEEDS_DIR / "question_reviews.json"),
        help="where decisions are kept (default: seeds/question_reviews.json)",
    )
    ap.add_argument("--review-ratio", type=float, default=quality.Thresholds.review_ratio)
    ap.add_argument("--block-ratio", type=float, default=quality.Thresholds.block_ratio)
    ap.add_argument("--min-per-level", type=int, default=DEFAULT_MINIMUM)
    ap.add_argument(
        "--max-share",
        type=float,
        help="exit 1 if %% of questions whose correct option is the longest is above this",
    )
    return ap.parse_args()


def apply_reviews(review_csv: str, reviews_file: str) -> int:
    with open(review_csv, newline="", encoding="utf-8") as f:
        filled = [row for row in csv.DictReader(f) if (row.get("decision") or "").strip()]
    decisions = []
    for row in filled:
        decision = row["decision"].strip().lower()
        if decision not in quality.DECISIONS:
            sys.exit(
                f"question {row['question_id']}: decision {decision!r} must be one of "
                f"{', '.join(quality.DECISIONS)}; nothing was saved"
            )
        decisions.append(
            {
                "question_id": int(row["question_id"]),
                "decision": decision,
                "reviewer": (row.get("reviewer") or "").strip(),
                "note": (row.get("note") or "").strip(),
            }
        )
    path = Path(reviews_file)
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {r["question_id"]: r for r in data["reviews"]}
    by_id.update({d["question_id"]: d for d in decisions})  # a newer decision replaces an older
    data["reviews"] = sorted(by_id.values(), key=lambda r: r["question_id"])
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(decisions)} decisions to {path} ({len(data['reviews'])} in total)")
    return 0


def main() -> int:
    args = _args()
    if args.apply_reviews:
        return apply_reviews(args.apply_reviews, args.reviews_file)

    limits = quality.Thresholds(review_ratio=args.review_ratio, block_ratio=args.block_ratio)
    rows = read_seed_rows(limits)
    skill_name = {s["skill_id"]: s["skill_name"] for s in rows["skills"]}
    subskill = {s["subskill_id"]: (s["skill_id"], s["subskill_name"]) for s in rows["subskills"]}
    options: dict[int, list[dict]] = defaultdict(list)
    for option in rows["options"]:
        options[option["question_id"]].append(option)

    total = longest = first_correct = 0
    statuses: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    active: dict[int, Counter[str]] = defaultdict(Counter)
    review_rows = []
    for q in rows["questions"]:
        skill_id, subskill_name = subskill[q["subskill_id"]]
        level, status = q["difficulty_level"].value, q["status"].value
        if status == "ACTIVE":
            active[skill_id][level] += 1
        if args.skill and skill_id not in args.skill:
            continue
        total += 1
        statuses[status] += 1
        issue_counts.update(q["quality_issues"])
        opts = sorted(options[q["question_id"]], key=lambda o: o["option_id"])
        question_in = quality.QuestionIn(
            q["question_id"],
            skill_id,
            q["question_text"],
            tuple(quality.Option(o["option_text"] or "", o["is_correct"]) for o in opts),
        )
        is_longest, _ = quality.length_ratio(question_in)
        longest += is_longest
        first_correct += bool(opts and opts[0]["is_correct"])
        if q["quality_issues"]:
            details = quality.check_question(question_in, limits)
            if "duplicate_question" in q["quality_issues"]:
                details.append(
                    quality.Issue(
                        "duplicate_question",
                        quality.Severity.BLOCK,
                        quality.ISSUE_TEXT["duplicate_question"],
                    )
                )
            review_rows.append(
                {
                    "question_id": q["question_id"],
                    "skill_id": skill_id,
                    "skill": skill_name[skill_id],
                    "subskill": subskill_name,
                    "level": level,
                    "status": status,
                    "issues": "; ".join(f"{i.severity.value}: {i.detail}" for i in details),
                    "question": q["question_text"],
                    "correct_option": " | ".join(o["option_text"] for o in opts if o["is_correct"]),
                    "wrong_options": " | ".join(
                        o["option_text"] for o in opts if not o["is_correct"]
                    ),
                    "decision": "",
                    "reviewer": "",
                    "note": "",
                }
            )

    share = 100 * longest / total if total else 0.0
    print(f"Questions checked: {total}")
    print(
        "Status: "
        + ", ".join(f"{s} {statuses[s]}" for s in ("ACTIVE", "NEEDS_REVIEW", "RETIRED"))
        + f"  (length limits: review {limits.review_ratio}x, block {limits.block_ratio}x)"
    )
    print(
        f"Correct option is the single longest: {longest} ({share:.1f}%)"
        " - unbiased would be about 25%"
    )
    print(
        f'Correct option is the first stored option ("A" before shuffling): {first_correct} '
        f"({100 * first_correct / total if total else 0:.1f}%) - the API shuffles options"
    )
    print("Issues found:")
    for code, count in issue_counts.most_common():
        print(f"  {count:5}  {code}: {quality.ISSUE_TEXT[code]}")

    print(f"\nActive questions per level (a skill needs {args.min_per_level} at every level):")
    print(f"  {'id':>3}  {'skill':<34} {'BEG':>4} {'JUN':>4} {'MID':>4} {'ADV':>4}  ready")
    ready_ids = []
    for skill_id in sorted(skill_name):
        if args.skill and skill_id not in args.skill:
            continue
        counts = active.get(skill_id, Counter())
        ready, short = quality.skill_readiness(dict(counts), args.min_per_level)
        if ready:
            ready_ids.append(skill_id)
        marks = " ".join(f"{counts.get(level, 0):4}" for level in quality.LEVELS)
        verdict = "ready" if ready else "short: " + ", ".join(f"{k} {v}" for k, v in short.items())
        print(f"  {skill_id:>3}  {skill_name[skill_id][:34]:<34} {marks}  {verdict}")
    print(f"\nSkills that can be tested: {len(ready_ids)} {ready_ids}")

    if args.review_file:
        review_rows.sort(
            key=lambda r: (
                r["status"] != "NEEDS_REVIEW",
                r["skill_id"],
                r["level"],
                r["question_id"],
            )
        )
        with open(args.review_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            writer.writerows(review_rows)
        print(f"\n{len(review_rows)} questions written to {args.review_file}")

    if args.max_share is not None and share > args.max_share:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
