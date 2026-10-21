"""Rewrite the WRONG options of length-biased questions so they match the correct one.

Nothing is written to the database. The script produces two files to review:
    rebalanced_review.csv   - old vs new wrong options, side by side
    rebalanced_updates.sql  - UPDATE statements; run it only after reviewing:
                              psql "$DATABASE_URL" -f rebalanced_updates.sql

Usage (reads DATABASE_URL and OPENAI_API_KEY from .env):
    python scripts/check_option_bias.py --csv biased.csv
    python scripts/rebalance_distractors.py biased.csv --limit 50

Use the same rules (DISTRACTOR_RULES below) in any prompt that GENERATES new
questions, so the bias doesn't come back.
"""

import argparse
import csv
import json
import os
import sys

import psycopg2
from dotenv import load_dotenv

DISTRACTOR_RULES = """Rules for the wrong options (distractors):
- Exactly 3 wrong options. Each must be clearly WRONG to an expert, but plausible to a beginner.
- Each wrong option must be about the SAME LENGTH as the correct option
  (within 20% of its character count) and use the same style, detail and grammar.
- The correct option must NOT be the longest or the most detailed / most "textbook" sounding.
- No "all of the above", "none of the above", jokes, or obviously silly options.
- Do not repeat words from the question only in the correct option (no give-away keywords)."""

SYSTEM = "You write high-quality multiple-choice distractors for technical skill assessments. Reply with JSON only."


def db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (see .env.example)")
    for prefix in ("postgresql+asyncpg://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix) :]
    return url


def make_client():
    from openai import OpenAI

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set (see .env.example)")
    return OpenAI(timeout=60)


def ask_model(client, question, correct, wrong, model):
    prompt = (
        f"Question: {question}\n"
        f"Correct answer ({len(correct)} characters): {correct}\n"
        f"Current wrong options (too short / too obvious): {json.dumps(wrong)}\n\n"
        f"{DISTRACTOR_RULES}\n\n"
        'Return JSON exactly like: {"wrong_options": ["...", "...", "..."]}'
    )
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        temperature=0.4,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    )
    data = json.loads(resp.choices[0].message.content)
    return [str(x).strip() for x in data.get("wrong_options", [])]


def acceptable(correct, new_wrong, n_needed):
    if len(new_wrong) != n_needed or len(set(new_wrong)) != n_needed:
        return False
    if any(w.lower() == correct.lower() for w in new_wrong):
        return False
    lo, hi = 0.8 * len(correct), 1.2 * len(correct)
    in_range = sum(1 for w in new_wrong if lo <= len(w) <= hi)
    # correct option must not be the single longest any more
    return in_range >= n_needed - 1 and max(len(w) for w in new_wrong) >= len(correct)


def sql_str(s):
    return "'" + s.replace("'", "''") + "'"


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("flagged_csv", help="CSV written by check_option_bias.py --csv")
    ap.add_argument(
        "--limit", type=int, default=25, help="how many questions to rewrite (worst first)"
    )
    ap.add_argument("--model", default="gpt-4o")
    ap.add_argument("--out-csv", default="rebalanced_review.csv")
    ap.add_argument("--out-sql", default="rebalanced_updates.sql")
    args = ap.parse_args()

    with open(args.flagged_csv, encoding="utf-8") as f:
        ids = [int(r["question_id"]) for r in csv.DictReader(f)][: args.limit]

    conn = psycopg2.connect(db_url())
    cur = conn.cursor()
    client = make_client()
    review, updates, skipped = [], [], []

    for qid in ids:
        cur.execute("SELECT question_text FROM questions WHERE question_id = %s", (qid,))
        row = cur.fetchone()
        if not row:
            continue
        cur.execute(
            "SELECT option_id, option_text, is_correct FROM options WHERE question_id = %s ORDER BY option_id",
            (qid,),
        )
        opts = cur.fetchall()
        correct = [o for o in opts if o[2]]
        wrong = [o for o in opts if not o[2]]
        if len(correct) != 1:
            skipped.append((qid, "not exactly one correct option"))
            continue
        new_wrong = []
        for _ in range(2):  # one retry if the model ignores the length rule
            try:
                new_wrong = ask_model(
                    client, row[0], correct[0][1], [w[1] for w in wrong], args.model
                )
            except Exception as e:  # network / JSON problems: skip this question
                print(f"  question {qid}: model call failed: {e}")
                new_wrong = []
            if acceptable(correct[0][1], new_wrong, len(wrong)):
                break
        if not acceptable(correct[0][1], new_wrong, len(wrong)):
            skipped.append((qid, "model output did not meet the length rules"))
            continue
        for (oid, old_text, _), new_text in zip(wrong, new_wrong, strict=True):
            review.append(
                {
                    "question_id": qid,
                    "question": row[0],
                    "correct_option": correct[0][1],
                    "option_id": oid,
                    "old_wrong_option": old_text,
                    "new_wrong_option": new_text,
                }
            )
            updates.append(
                f"UPDATE options SET option_text = {sql_str(new_text)} "
                f"WHERE option_id = {oid} AND question_id = {qid} AND is_correct = false;"
            )
        print(f"  question {qid}: rewritten")
    conn.close()

    with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "question_id",
                "question",
                "correct_option",
                "option_id",
                "old_wrong_option",
                "new_wrong_option",
            ],
        )
        w.writeheader()
        w.writerows(review)
    with open(args.out_sql, "w", encoding="utf-8") as f:
        f.write(
            '-- Review rebalanced_review.csv first. Then: psql "$DATABASE_URL" -f '
            + args.out_sql
            + "\n"
        )
        f.write("BEGIN;\n" + "\n".join(updates) + "\nCOMMIT;\n")
    print(
        f"\n{len(set(r['question_id'] for r in review))} questions rewritten, {len(skipped)} skipped"
    )
    for qid, why in skipped:
        print(f"  skipped {qid}: {why}")
    print(f"Review {args.out_csv}, then apply {args.out_sql}")


if __name__ == "__main__":
    main()
