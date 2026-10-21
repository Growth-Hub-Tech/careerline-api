#!/usr/bin/env bash
# Entry point for Render and Docker: migrate the database, then start the API.
# If the migration fails the script exits non-zero and the server never starts.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running database migrations..."
alembic upgrade head

echo "Starting careerline-api on port ${PORT:-8000}..."
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --no-access-log
