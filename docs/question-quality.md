# Question quality and the experts' review (Day 8)

Every question in `seeds/questions/` goes through one check, `app/services/question_quality.py`. The seed loader runs it on every load and stores each question's `status` and `quality_issues`; `scripts/check_questions.py` runs the same check and writes the review file for the experts.

## What is checked

| Issue | Severity | Meaning |
|---|---|---|
| `no_single_correct` | block | not exactly one correct option |
| `too_few_options` | block | fewer than 3 options |
| `empty_option` | block | an option with no text |
| `duplicate_option` | block | two options with the same text |
| `duplicate_question` | block | the same question text earlier in the same skill (the first copy stays) |
| `length_giveaway` | review at 1.3x, block at 2.0x | the correct option is the single longest and that many times the average wrong option, so a learner can pick it without knowing the answer |
| `all_none_of_the_above` | review | "all/none of the above" options |
| `not_four_options` | review | 3 or 5+ options |

`length_giveaway` is the old `check_option_bias.py` check. The two limits are settings (`QUESTION_LENGTH_REVIEW_RATIO`, `QUESTION_LENGTH_BLOCK_RATIO`).

## Statuses

- **ACTIVE**: served in tests. It may still have review notes.
- **NEEDS_REVIEW**: has a blocking issue; never served until the question is fixed in its seed file or an expert approves it (approval is allowed for `length_giveaway`, `all_none_of_the_above` and `not_four_options`; a broken question must be fixed).
- **RETIRED**: an expert rejected it; never served.

A skill can be tested only when **every level has at least 15 ACTIVE questions** (`MIN_ACTIVE_QUESTIONS_PER_LEVEL`). `GET /skills/` shows `testable`, and `POST /attempts/start` refuses the others with `409 skill_not_ready`.

## Where the bank stands (seed files of 30 Oct)

- 4,000 questions: 2,362 ACTIVE, 1,638 NEEDS_REVIEW, 0 RETIRED.
- The correct option is the single longest in 82.5% of questions (about 25% is unbiased). 2,864 questions have a length give-away; 1,612 of them are strong enough (2.0x or more) to block.
- Also: 57 "all/none of the above", 30 duplicate questions, 1 duplicate option.
- **14 skills can be tested**: 1 Frontend Web Development, 2 Backend Development, 7 API Design & Integration, 20 Machine Learning, 21 Deep Learning & AI, 24 NLP, 25 Computer Vision, 30 Prompt Engineering, 35 RevOps, 36 Cold Outreach & Prospecting, 37 Negotiation & Closing, 38 Sales Analytics & Forecasting, 39 Digital Marketing, 40 Content Marketing. Skills 41 to 50 have no questions yet.
- With the old strict limit (block at 1.3x) **no skill** could be tested. That is why blocking starts at 2.0x for now; tighten it as the experts fix questions.

Run `python scripts/check_questions.py` for the per-skill table (active questions per level and how many each level is short).

## The experts' review

1. Make the file: `python scripts/check_questions.py --review-file review.csv` (all skills) or with `--skill 3 --skill 19` for some skills. `docs/question-review-pilot-skills.csv` is this file for the 21 skills of the 8 pilot roles. Blocked questions come first.
2. Experts fill in `decision` (`approved` or `rejected`), `reviewer` and `note`. Best of all, fix the question in its seed file instead. For a length give-away, rewrite the wrong options to the same length and style (`scripts/rebalance_distractors.py review.csv` drafts new ones to review).
3. Save the decisions: `python scripts/check_questions.py --apply-reviews review.csv`. They go into `seeds/question_reviews.json`. Commit the file in a pull request; the next seed load gives those questions their new status.

Quickest way to make a pilot skill testable: the per-skill table shows how many questions each level is short (e.g. Version Control: BEGINNER 2). Review that level's blocked questions first.
