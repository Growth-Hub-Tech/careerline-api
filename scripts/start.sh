#!/usr/bin/env bash
# Entry point for Render: migrate the database, load the seed files (if SEED_ON_START=true),
# then start the API.
# If the migration fails the script exits non-zero and the server never starts.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running database migrations..."
alembic upgrade head

# The test server reloads the question bank on every deploy (safe to repeat: see app/db/seed.py).
# Off unless SEED_ON_START=true, so production data is only changed on purpose.
if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "Loading seed files..."
  python -m app.db.seed
fi

# The test server's demo accounts and demo company (docs/api.md, "Demo accounts"). Never in
# production: app/db/demo.py refuses to run there.
if [ "${DEMO_DATA_ON_START:-false}" = "true" ]; then
  echo "Loading demo accounts..."
  python -m app.db.demo
fi

echo "Starting careerline-api on port ${PORT:-8000}..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --no-access-log
