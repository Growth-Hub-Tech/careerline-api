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
    deps.py          shared dependencies: get_db, get_current_learner, require_same_learner
    routes/          one module per resource (auth, learners, skills, attempts, recommendations),
                     plus health (/healthz, /readyz) and legacy (/api/*, deprecated)
  core/              config, security, logging, exceptions, error handlers, response envelope, middleware
  db/                SQLAlchemy base, engine/session, migration check
  integrations/      external services (OpenAI)
  models/            SQLAlchemy models
  repositories/      database queries
  schemas/           Pydantic request/response models
  services/          business logic (attempts, scoring, recommendations)
migrations/          Alembic environment and versions
scripts/             start.sh (Render entry point), data tools, sql/
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
- **Legacy routes.** The old `/api/*` routes are deprecated, keep their old success bodies and are removed on Day 4.

## Database migrations

- `scripts/start.sh` runs `alembic upgrade head` before starting the server. If the migration fails, the server never starts.
- On startup the app also checks that the database is at the latest migration and refuses to start if it is behind, even when someone runs `uvicorn` directly (`CHECK_MIGRATIONS_ON_STARTUP`).
- Migrations take a Postgres advisory lock, so two instances starting together never migrate at once.
- Create one with `alembic revision --autogenerate -m "add x to y"`, review the generated file, and run `alembic upgrade head`. CI fails when there is more than one Alembic head.

## Logging

`app/core/logging.py` configures structlog. With `LOG_JSON=true` (Render) each line is one JSON object; locally you get readable, coloured lines. Use `get_logger(__name__)` and log events with fields: `logger.info("attempt_scored", attempt_id=..., percentage=...)`. Never log tokens, passwords, emails or request bodies.

## Quality checks

```bash
ruff check .          # lint
ruff format .         # format
mypy                  # type-check app/
pytest                # tests
```

CI (`.github/workflows/ci.yml`) runs on every pull request into `dev` or `main`:

- lint, format and types
- migrating an empty Postgres database to head and starting the app on it
- the tests
- a dependency audit (report only)

A pull request into `main` must come from `dev`.

## Branches and releases

- `dev` is the default branch. Work happens on `type/description` branches cut from `dev`, and lands in `dev` through a pull request.
- `main` is production. It only receives pull requests from `dev`.
- The GitHub organisation is on the Free plan, so GitHub itself can't enforce branch protection on this private repo. CI checks every pull request; nothing technically stops a direct push to `dev` or `main`, so don't.

## Deployment (Render)

`render.yaml` defines the web service: `pip install -r requirements.txt`, then `bash scripts/start.sh`, with a health check on `/healthz`. Set `DATABASE_URL`, `SECRET_KEY`, `OPENAI_API_KEY` and `CORS_ORIGINS` in the Render dashboard.

## Environment variables

Every variable the code reads is listed in [.env.example](.env.example). The required ones:

| Variable       | Description                                                        |
| -------------- | ------------------------------------------------------------------ |
| `DATABASE_URL` | Postgres connection string                                         |
| `SECRET_KEY`   | Signs login tokens (JWT); a long random value                      |
| `CORS_ORIGINS` | Comma-separated frontend origins (default `http://localhost:5173`) |
| `LOG_JSON`     | `true` in production for JSON logs                                 |

## Scripts

- `scripts/check_option_bias.py`: reports questions whose correct option gives itself away by its length.
- `scripts/rebalance_distractors.py`: drafts rewritten wrong options for human review. It never writes to the database.
- `scripts/migrate_mysql_to_postgres.py`: the one-off copy from the old MySQL database.
- `scripts/sql/`: repair SQL (`reset_sequences.sql`, `fix_learner_levels.sql`) and the old MySQL dump.
  - The dump contains real people's personal details. It is turned into seed files and deleted on Day 4.

## Built by

Joshua Mudana, AI/ML Engineer, GrowthHub/Salesplat
