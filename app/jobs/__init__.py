"""Background jobs: a Postgres-backed queue (app/jobs/queue.py), handlers registered by kind
(app/jobs/registry.py) and the runner that claims and runs them (app/jobs/runner.py).

Run them with `python -m app.worker` (a worker service), or inside the web process with
RUN_JOBS_IN_WEB=true (the free test server, which has no worker service).
"""
