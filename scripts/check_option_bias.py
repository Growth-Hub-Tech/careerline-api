"""Report questions where the correct option gives itself away by its LENGTH
(and, for information, by its stored POSITION).

Why: in a 4-option question the correct answer should be the longest one about
25% of the time. Here it is the longest in ~83% of questions, so a learner who
always picks the longest option passes without knowing anything. Shuffling the
option order does NOT fix this, because length is visible in any order.

Position: in the stored data the correct option is usually the FIRST one inserted
(lowest option_id, i.e. "A"). The API already shuffles options when it serves a
question, so learners don't see that pattern; the report shows it anyway so you
can keep the shuffle in place (don't remove it from get_options_for_question).

Usage (reads DATABASE_URL from .env):
    python scripts/check_option_bias.py                      # summary
    python scripts/check_option_bias.py --csv biased.csv     # + list of flagged questions
    python scripts/check_option_bias.py --max-share 35       # exit 1 if share > 35% (for CI)

A question is FLAGGED when the correct option is the single longest AND it is
at least --ratio times (default 1.3) the average distractor length.
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

import psycopg2
from dotenv import load_dotenv


def db_url():
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (see .env.example)")
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
    return url


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="write flagged questions to this CSV file")
    ap.add_argument("--ratio", type=float, default=1.3, help="flag if correct >= ratio x average distractor length")
    ap.add_argument("--max-share", type=float, help="exit 1 if %% of questions with longest-correct is above this")
    args = ap.parse_args()

    conn = psycopg2.connect(db_url())
    cur = conn.cursor()
    cur.execute("""
        SELECT q.question_id, s.skill_name, q.difficulty_level::text, q.question_text,
               o.option_id, o.option_text, o.is_correct
        FROM questions q
        JOIN subskills ss ON ss.subskill_id = q.subskill_id
        JOIN skills s ON s.skill_id = ss.skill_id
        JOIN options o ON o.question_id = q.question_id
        ORDER BY q.question_id, o.option_id
    """)
    questions = {}
    for qid, skill, level, qtext, oid, otext, correct in cur.fetchall():
        q = questions.setdefault(qid, {"skill": skill, "level": level, "text": qtext, "options": []})
        q["options"].append((oid, (otext or "").strip(), bool(correct)))
    conn.close()

    total = longest = flagged_n = 0
    first_correct = 0  # correct option is the first stored one (lowest option_id)
    by_group = defaultdict(lambda: [0, 0])  # (skill, level) -> [questions, longest-correct]
    flagged = []
    problems = []
    for qid, q in questions.items():
        correct = [o for o in q["options"] if o[2]]
        wrong = [o for o in q["options"] if not o[2]]
        if len(correct) != 1 or not wrong:
            problems.append((qid, len(correct), len(q["options"])))
            continue
        total += 1
        if q["options"][0][2]:
            first_correct += 1
        c_len = len(correct[0][1])
        w_lens = [len(o[1]) for o in wrong]
        is_longest = c_len > max(w_lens)
        avg_w = sum(w_lens) / len(w_lens)
        ratio = c_len / avg_w if avg_w else float("inf")
        g = by_group[(q["skill"], q["level"])]
        g[0] += 1
        if is_longest:
            longest += 1
            g[1] += 1
        if is_longest and ratio >= args.ratio:
            flagged_n += 1
            flagged.append({
                "question_id": qid, "skill": q["skill"], "level": q["level"],
                "correct_len": c_len, "longest_wrong_len": max(w_lens),
                "avg_wrong_len": round(avg_w, 1), "ratio": round(ratio, 2),
                "question": q["text"], "correct_option": correct[0][1],
                "wrong_options": " | ".join(o[1] for o in wrong),
            })

    share = 100 * longest / total if total else 0
    expected = 100 / 4
    print(f"Questions checked: {total}")
    print(f"Correct option is the single longest: {longest} ({share:.1f}%)  - unbiased would be about {expected:.0f}%")
    print(f"Correct option is the first stored option (\"A\" before shuffling): {first_correct} "
          f"({100 * first_correct / total if total else 0:.1f}%)  - the API shuffles options when serving")
    print(f"Flagged (longest AND >= {args.ratio}x average wrong option): {flagged_n}")
    if problems:
        print(f"Questions with != 1 correct option or no wrong options: {len(problems)} (ids: {[p[0] for p in problems[:20]]})")
    print("\nWorst skill/level groups (share of questions where the longest option is correct):")
    worst = sorted(by_group.items(), key=lambda kv: kv[1][1] / kv[1][0], reverse=True)[:15]
    for (skill, level), (n, longest) in worst:
        print(f"  {100 * longest / n:5.1f}%  {skill} / {level}  ({longest}/{n})")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            fields = ["question_id", "skill", "level", "correct_len", "longest_wrong_len", "avg_wrong_len",
                      "ratio", "question", "correct_option", "wrong_options"]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(sorted(flagged, key=lambda r: -r["ratio"]))
        print(f"\nFlagged questions written to {args.csv}")

    if args.max_share is not None and share > args.max_share:
        sys.exit(1)


if __name__ == "__main__":
    main()
