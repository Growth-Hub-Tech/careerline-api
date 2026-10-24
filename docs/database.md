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

The reference data the app needs, as JSON files in the repo: the 4 proficiency levels and their score bands, 50 skills with 221 subskills, 4000 questions with 16000 options (one file per skill in `seeds/questions/`), and 10 behavioural questions. They came from the question tables of the old MySQL dump, without any of its personal data.

```bash
python -m app.db.seed     # load into DATABASE_URL; prints inserted / updated / unchanged per table
```

- **Safe to run twice.** Every row is upserted on its id from the file. The second run changes nothing.
- **The files win.** A question edited directly in the database is put back to what the file says on the next load. Change questions in the seed files, through a pull request, then load.
- **Nothing else is touched.** Rows not in the files stay (old attempts may point at them), learners' data is never read or changed, and the id counters are moved past the highest id so new rows get fresh ids.
- **On Render** the test server loads them on every deploy (`SEED_ON_START=true`). Production only loads them when someone runs the command.

Before the first load on a database that already has questions (the Render test database was filled by the old MySQL copy script, with the same ids), compare first if anyone edited questions there by hand (e.g. with `scripts/rebalance_distractors.py` output): the load would put the file version back.
