FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY app ./app
COPY migrations ./migrations
COPY scripts/start.sh ./scripts/start.sh

# Never run as root
RUN useradd --create-home --uid 10001 appuser
USER appuser

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/healthz', timeout=4)"

# Migrates the database, then starts the server (exits non-zero if migrations fail)
CMD ["bash", "scripts/start.sh"]
