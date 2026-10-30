# careerline-api

The backend for CareerLine AI. It tests learners across tech and revenue skills, scores them, confirms proficiency levels and generates personalised learning pathways.

## Stack

- **Python 3.13**, **FastAPI**, **Pydantic v2**
- **PostgreSQL 16**, **SQLAlchemy 2** (async, asyncpg), **Alembic** migrations
- **structlog** for logging (JSON in production)
- **OpenAI** for recommendation wording (optional; a plain fallback is used without a key)
- Quality gates: **ruff** (lint + format), **mypy**, **pytest**, **GitHub Actions**

## Project layout

```
app/
  main.py            create_app(): settings, logging, middleware, error handlers, routers, lifespan
  api/
    deps.py          shared dependencies: get_db, get_current_session, get_current_learner
    routes/          one module per resource (auth, learners, skills, attempts, recommendations),
                     plus health (/healthz, /readyz)
  core/              config, security, logging, exceptions, error handlers, response envelope, middleware
  db/                SQLAlchemy base, engine/session, migration check, seed loader (python -m app.db.seed)
  email/             send_email(), backends (smtp, test mailbox, console), templates/ (one layout)
  integrations/      external services (OpenAI)
  jobs/              background jobs: Postgres queue, handler registry, runner
  models/            SQLAlchemy models
  repositories/      database queries
  schemas/           Pydantic request/response models
  services/          business logic (attempts, scoring, recommendations)
  sample/            sample answers for endpoints not built yet (see "Sample API")
  worker.py          background worker: runs the jobs (python -m app.worker)
migrations/          Alembic environment and the one starting migration
seeds/               reference data: levels, skills, subskills, questions and options (JSON)
scripts/             start.sh (Render entry point), export_openapi.py, data tools, sql/
docs/                api.md (for the frontend), database.md (migrations and seeds)
openapi.json         the API contract the frontend generates types from
tests/
```

## Setup

You need Python 3.13 and a Postgres database.

```bash
git clone https://github.com/Growth-Hub-Tech/tech-assessment-service.git
cd tech-assessment-service
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env               # then set DATABASE_URL and SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload      # http://localhost:8000
```

API docs: http://localhost:8000/docs (OpenAPI at `/openapi.json`).

## API conventions

- **Global prefix.** Every API route is served under `API_PREFIX` (default `/api/v1`), which `app/main.py` adds once. Route files and folders never repeat it. `/healthz`, `/readyz`, `/docs` and `/openapi.json` sit outside the prefix.
- **Success envelope.** Routes return their data; `EnvelopeRoute` wraps it:
  ```json
  { "success": true, "message": "Learner registered successfully", "data": { "learner_id": 1 } }
  ```
  Return `ok(data, message="...")` from `app/core/responses.py` to set a message. The exception is `POST /api/v1/auth/login`: it returns the standard OAuth2 token body, so the "Authorize" button in `/docs` and OAuth2 clients work.
- **Error envelope.** Every error, including validation errors and unknown routes, looks like this:
  ```json
  {
    "success": false,
    "error": { "code": "not_found", "message": "Attempt 9 not found", "request_id": "…" }
  }
  ```
  Raise `NotFoundError`, `ForbiddenError`, `ConflictError`, etc. from `app/core/exceptions.py`. Unhandled exceptions return a generic 500 and are logged with their traceback; internals are never sent to the client. Validation errors list `details` without echoing the submitted values.
- **Request ids.** Every response has an `X-Request-ID` header (an incoming one is reused when it is safe). The same id is in every log line and in the error body.

## Sample API

Endpoints that are not built yet answer with realistic, typed **sample data** (`app/sample/`), on their real `/api/v1` path, in the real envelope, with the real response model (`app/schemas/`). The frontend builds against them now; when a feature is built for real, its route moves to `app/api/routes` with the same path and model, the sample route is deleted, and the frontend changes nothing.

- **Marked.** Every sample response (errors too) has the header `X-Sample-Data: true`, successes have `"message": "Sample data"`, and in `/docs` and `openapi.json` sample operations are tagged `Sample: …` with `x-sample: true`.
- **Edge cases on demand.** Send `X-Mock-Scenario` to force one: `unauthenticated` (401), `payment_required` (402), `forbidden` (403), `not_found` (404), `conflict` (409), `expired` (410), `validation_error` (422), `rate_limited` (429), `server_error` (500), `unavailable` (503) and `slow` (2 s delay) work on every sample route; `empty`, `pending`, `paid`, … only where the route lists them (`x-sample-scenarios`). An unknown scenario is a 400.
- **Login.** Protected sample routes need a real token from `POST /api/v1/auth/login`; the token is checked but no account is looked up.
- **Never in the way.** A sample route can't have the same method and path as a real one (a test checks it), and real routes are mounted first.
- **On or off.** `SAMPLE_API_ENABLED` (unset = on everywhere except `APP_ENV=production`).

## API description (openapi.json)

`openapi.json` at the repo root is the whole contract, real and sample endpoints, for the frontend to generate TypeScript types from (see `docs/api.md`). After changing any route or response model:

```bash
python scripts/export_openapi.py          # regenerate, then commit openapi.json
python scripts/export_openapi.py --check  # what CI runs
```

CI and `tests/test_openapi_file.py` fail when the committed file is out of date.

## Database migrations

- `scripts/start.sh` runs `alembic upgrade head` before starting the server. If the migration fails, the server never starts.
- On startup the app also checks that the database is at the latest migration and refuses to start if it is behind, even when someone runs `uvicorn` directly (`CHECK_MIGRATIONS_ON_STARTUP`).
- Migrations take a Postgres advisory lock, so two instances starting together never migrate at once.
- Create one with `alembic revision --autogenerate -m "add x to y"`, review the generated file, and run `alembic upgrade head`. CI fails when there is more than one Alembic head.
- Since Day 4 there is a single starting migration; see [docs/database.md](docs/database.md) for what that means for databases created before.

## Seed files

`seeds/` holds the reference data (4 levels, score bands, 50 skills, 221 subskills, 4000 questions with their options, behavioural questions). `python -m app.db.seed` loads it; running it again changes nothing. The test server loads it on every deploy (`SEED_ON_START=true`). Details: [docs/database.md](docs/database.md).

`python -m app.db.demo` loads the demo accounts and Demo Company Ltd (listed in [docs/api.md](docs/api.md)); the test server runs it on every deploy (`DEMO_DATA_ON_START=true`), and it refuses to run in production.

Access: every route has one rule in `app/core/permissions.py` (public, signed in, self, or an organisation permission per role); a new route needs one, or the tests fail and the route is refused.

## Logging

`app/core/logging.py` configures structlog. With `LOG_JSON=true` (Render) each line is one JSON object; locally you get readable, coloured lines. Use `get_logger(__name__)` and log events with fields: `logger.info("attempt_scored", attempt_id=..., percentage=...)`. Never log tokens, passwords, emails or request bodies.

## Quality checks

```bash
ruff check .          # lint
ruff format .         # format
mypy                  # type-check app/
pytest                # tests
python scripts/export_openapi.py --check  # openapi.json matches the code
```

### Tests

- `tests/test_app.py`, `tests/test_db_guard.py`: fast unit tests, no database needed.
- `tests/sample/`: the sample API (marker, scenarios, every sample endpoint, the checkout and invitation flows), no database needed.
- `tests/test_worker_and_cors.py`, `tests/test_render_blueprint.py`: the worker, CORS and `render.yaml`.
- `tests/integration/`: the real API on a real Postgres test database (register, login, attempts, scoring, recommendations, ownership, error envelopes). Open bugs are in `tests/integration/test_known_bugs.py`, marked `xfail(strict=True)`: they show as `xfailed` until the bug is fixed, then turn the run red so the marker gets removed.

The integration tests only run when `TEST_DATABASE_URL` is set, and they refuse to start unless it is a local database with `test` in its name (never the one in `.env`). They create the database if it is missing, migrate it to head and empty every table before each test.

```bash
# Postgres in Docker (or use any local Postgres user that can create databases)
docker run -d --name careerline-test-db -e POSTGRES_PASSWORD=postgres -p 5433:5432 postgres:16

export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/careerline_test
pytest
```

Without `TEST_DATABASE_URL`, `pytest` runs the unit tests and skips the database ones. In CI a missing `TEST_DATABASE_URL` is an error.

CI (`.github/workflows/ci.yml`) runs on every pull request into `dev` or `main`:

- lint, format and types, and that `openapi.json` is up to date
- migrating an empty Postgres database to head and starting the app on it
- the tests, including the database integration tests (on their own database in the Postgres service)
- a secret scan of the current files with gitleaks (not the git history)
- a dependency audit (report only)

A pull request into `main` must come from `dev`.

## Branches and releases

- `dev` is the default branch. Work happens on `type/description` branches cut from `dev`, and lands in `dev` through a pull request.
- `main` is production. It only receives pull requests from `dev`.
- The GitHub organisation is on the Free plan, so GitHub itself can't enforce branch protection on this private repo. CI checks every pull request; nothing technically stops a direct push to `dev` or `main`, so don't.

## Deployment (Render)

`render.yaml` is a Render Blueprint for the test server: the web service (`pip install -r requirements.txt`, then `bash scripts/start.sh`, which migrates before starting, health check on `/healthz`), a background worker (`python -m app.worker`, runs the background jobs; on the free plan set `RUN_JOBS_IN_WEB=true` on the web service instead) and a Postgres 16 database. Render generates `SECRET_KEY`; set `CORS_ORIGINS` (the website's address) and optionally `OPENAI_API_KEY` in the dashboard. See [docs/api.md](docs/api.md#test-server-render).

## API docs for the frontend

[docs/api.md](docs/api.md): base URLs, login, envelopes and error codes, sample data and `X-Mock-Scenario`, generating TypeScript types from `openapi.json`, and how API changes are announced (changelog, `api-change` label).

## Environment variables

Every variable the code reads is listed in [.env.example](.env.example). The required ones:

| Variable       | Description                                                        |
| -------------- | ------------------------------------------------------------------ |
| `DATABASE_URL` | Postgres connection string                                         |
| `SECRET_KEY`   | Signs login tokens (JWT) and keys the rate-limit hashes; long, random |
| `CORS_ORIGINS` | Comma-separated frontend origins (default `http://localhost:5173`) |
| `LOG_JSON`     | `true` in production for JSON logs                                 |

Accounts: passwords are hashed with Argon2id (older bcrypt hashes still work and are upgraded at sign-in); sessions are rows in `auth_sessions`. Settings: `VERIFY_EMAIL_TOKEN_HOURS`, `PASSWORD_RESET_TOKEN_MINUTES`, `LOGIN_MAX_FAILURES_PER_EMAIL`, `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_WINDOW_MINUTES`, `SIGNUPS_PER_IP_PER_HOUR`.

Background jobs: `RUN_JOBS_IN_WEB` (run them inside the API, for a server with no worker), `JOB_*` (polling, lease, retries). Email: `EMAIL_BACKEND` (`smtp`, `test_mailbox`, `console`), `EMAIL_FROM`, `SUPPORT_EMAIL`, `FRONTEND_URL`, `SMTP_*`, `TEST_MAILBOX_TOKEN`.

### Email layout

Every email is rendered inside `app/email/templates/layout.html` (and `layout.txt` for the plain-text part). That pair is the only place that decides how emails look. Omotoke's email design replaces those two files, keeping the slot names documented at the top of `layout.html` (`content`, `preheader`, `footer_note`, `brand.*`).

## Scripts

- `scripts/simulate_adaptive.py`: simulates 1,000 people per level through the adaptive test engine and prints how well the scores separate the levels (docs/adaptive-engine.md).
- `scripts/check_questions.py`: the question-quality check (Day 8): each question's issues and status, which skills can be tested, and the experts' review file (`--review-file`, then `--apply-reviews`). See docs/question-quality.md.
- `scripts/rebalance_distractors.py`: drafts rewritten wrong options for human review. It never writes to the database.
- `scripts/sql/`: one-off repair SQL for databases copied from the old MySQL database (`reset_sequences.sql`, `fix_learner_levels.sql`).

## Built by

Joshua Mudana, AI/ML Engineer, GrowthHub/Salesplat
