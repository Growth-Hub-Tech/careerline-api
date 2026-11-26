#!/usr/bin/env bash
# Entry point for the server: migrate the database, load the seed files and demo data (test
# server only, APP_ENV=staging), then start the API.
# If the migration fails the script exits non-zero and the server never starts.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running database migrations..."
alembic upgrade head

# The test server reloads the question bank and its demo accounts and demo company (docs/api.md,
# "Demo accounts") on every deploy; both are safe to repeat (app/db/seed.py, app/db/demo.py).
# Production data is only changed on purpose: run `python -m app.db.seed` there by hand, and
# app/db/demo.py refuses to run there at all.
if [ "${APP_ENV:-development}" = "staging" ]; then
  echo "Loading seed files..."
  python -m app.db.seed
  echo "Loading demo accounts..."
  python -m app.db.demo
fi

echo "Starting careerline-api on port ${PORT:-8000}..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 2 \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --no-access-log
