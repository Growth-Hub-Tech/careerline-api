# Database: migrations and seed files

## Migrations

There is one starting migration, `migrations/versions/b7d24e6f0c13_initial_schema.py`, that creates every table and enum type. It replaced four hand-built migrations on Day 4; the schema is exactly the same (checked with `pg_dump --schema-only` on Postgres 16). Later changes are migrations on top of it, in one straight line:

| Revision | Day | What it does |
| --- | --- | --- |
| `c5a1d0e7b2f4` | 5 | `background_jobs` (the job queue) |
| `d2e8f1a4c6b9` | 5 | `email_outbox`, `test_mailbox_messages` |
| `e4b7c9d1f3a2` | 5 | `contact_messages`, `rate_limit_events` |
| `f6c3a8e2d5b1` | 6 | `auth_sessions`, `account_tokens`, `learner.email_verified_at` |
| `a7d4e9b2c8f3` | 7 | `organisations`, `organisation_members` (role owner/admin/recruiter) |
| `b8e3f1c6d2a9` | 8 | `questions.status` (ACTIVE/NEEDS_REVIEW/RETIRED) and `questions.quality_issues`; `job_roles`, `job_role_skills`, `job_titles` |
| `c4f7a2d9e1b3` | 10 | The adaptive test: `test_attempt.test_format` (existing rows become `fixed`), `question_count`, `expires_at`, `ability`, `confidence`, `ended_by`, status `EXPIRED`; `attempt_question.level`, `served_at`, `selected_option_id`, `is_correct`, `answered_at`; `skill_history` (one row per finished test). Old attempts keep everything they had. |
| `d9a4b6e1f2c7` | 11 | `question_explanations`: one AI explanation per question (kept for everyone), with a fingerprint of the question, options and right answer it was written for. New empty table. |
| `e3c7f9a1b5d8` | 12 | `result_reports`: the PDF skill report of a result (status generating/ready/failed, the PDF itself, a version that goes up when it is made again). New empty table. |
| `f1b8d4c2a6e9` | 13 | `beginner_intakes`: every beginner-path intake (questionnaire version, answers) with the career paths it gave. New empty table. |
| `a3f5c8e1d7b2` | 14 | `programmes`, `programme_roles`, `programme_skills` (reference data from `seeds/programmes.json`, filled by the seed loader) and `programme_clicks` (every click on a programme, for referral reporting). New tables. |
| `b6d2e9f4a1c7` | 16 | `credit_packs` (from `seeds/credit_packs.json`), `payments` (one Paystack checkout each), `credit_balances` and `credit_transactions` (each person's credits and every change; a payment's credits are added by one transaction, ever), `paystack_events` (every webhook event once). New tables. |
| `c8e4a2f6b9d3` | 17 | `test_prices` (from `seeds/test_prices.json`; a skill not listed is free) and `credit_transactions.attempt_id` (the test a charge or refund was for; one of each per test). New table and an empty new column. |
| `d4f9b3a7c2e8` | 18 | `learner_consents`, `consent_events` (every consent change), `data_exports` (a copy of a person's data, kept 7 days), `account_deletions` (scheduled, cancelled or completed). New empty tables. |

- `scripts/start.sh` runs `alembic upgrade head` on every start (every Render deploy). If it fails, the server never starts.
- New change: edit the models, `alembic revision --autogenerate -m "add x to y"`, read the generated file, `alembic upgrade head`. CI fails with more than one head.
- `tests/integration/test_migrations_on_postgres.py` fails if the models and the migrations ever disagree.

### Databases created before Day 4 (the Render test database)

The new migration reuses the old head's revision id, `b7d24e6f0c13`, so a database that the old chain migrated to the end is already at head: nothing runs, nothing to do. Check before deploying:

```bash
DATABASE_URL=<the Render database's External URL> alembic current
# b7d24e6f0c13 (head)   -> fine, deploy as normal
```

If it shows one of the old ids (`38a2cb03e747`, `e17f129e4f88`, `a1f3c9d2e801`), the database is behind the old chain; that database can't be upgraded by the new migration. The simplest fix for a test database is a reset: drop everything and let the next deploy create it (`alembic upgrade head`) and load the seeds (`SEED_ON_START=true`). It deletes all learners and attempts on that database.

## Seed files (`seeds/`)

The reference data the app needs, as JSON files in the repo: the 4 proficiency levels and their score bands, 50 skills with 221 subskills, 4000 questions with 16000 options (one file per skill in `seeds/questions/`), 10 behavioural questions, and (Day 8) the 8 pilot job roles with their skills (`job_roles.json`), the job-title ladder (`job_titles.json`) and the experts' decisions on flagged questions (`question_reviews.json`). `beginner_intake.json` (Day 13) is the beginner-path questionnaire with each option's points per job role; the app reads it directly (it is not loaded into a table). `programmes.json` (Day 14) is the programme catalogue with the roles and skills each covers (prices in kobo). It is a placeholder catalogue: the real programmes, prices and links replace it before launch. A programme taken out of the file is retired (hidden), not deleted. `credit_packs.json` (Day 16) is what credits cost; a pack taken out stops being sold. `test_prices.json` (Day 17) is what each test costs in credits; a skill taken out is free again. They came from the question tables of the old MySQL dump, without any of its personal data.

```bash
python -m app.db.seed     # load into DATABASE_URL; prints inserted / updated / unchanged per table
```

- **Safe to run twice.** Every row is upserted on its id from the file. The second run changes nothing.
- **The files win.** A question edited directly in the database is put back to what the file says on the next load. Change questions in the seed files, through a pull request, then load.
- **Nothing else is touched.** Rows not in the files stay (old attempts may point at them), learners' data is never read or changed, and the id counters are moved past the highest id so new rows get fresh ids.
- **Question statuses are worked out on every load.** The question-quality check (docs/question-quality.md) runs over the files and stores each question's `status` and `quality_issues`; only `ACTIVE` questions are served. To change a status, fix the question or record an expert decision, then load.
- **On Render** the test server loads them on every deploy (`SEED_ON_START=true`). Production only loads them when someone runs the command.

Before the first load on a database that already has questions (the Render test database was filled by the old MySQL copy script, with the same ids), compare first if anyone edited questions there by hand (e.g. with `scripts/rebalance_distractors.py` output): the load would put the file version back.
