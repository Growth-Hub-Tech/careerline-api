"""The Render test server: the worker starts and stops cleanly, CORS lets the website in."""

import asyncio
import os
import signal
import subprocess
import sys
import time

import pytest

from app import worker
from app.core.config import Settings, settings


async def test_the_worker_stops_cleanly_when_asked(monkeypatch):
    checks = []

    async def fake_check() -> bool:
        checks.append(True)
        return True

    monkeypatch.setattr(worker, "check_database", fake_check)
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop, heartbeat_seconds=0.01))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert len(checks) >= 2  # the start check and at least one heartbeat


def test_the_worker_process_starts_and_exits_on_sigterm():
    # No database here: the worker logs that and keeps running until Render stops it
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql://nobody:nothing@127.0.0.1:1/none",
        "LOG_JSON": "true",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "app.worker"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        output = ""
        while "worker_database_unreachable" not in output and time.monotonic() < deadline:
            line = process.stdout.readline() if process.stdout else ""
            output += line
        assert "worker_started" in output
        process.send_signal(signal.SIGTERM)
        rest, _ = process.communicate(timeout=10)
        assert process.returncode == 0
        assert "worker_stopped" in rest
    finally:
        if process.poll() is None:
            process.kill()


async def test_cors_allows_the_website_origin(client):
    origin = settings.CORS_ORIGINS[0]
    response = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin


async def test_cors_refuses_other_origins(client):
    response = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://careerline.example.com", ["https://careerline.example.com"]),
        (
            "https://careerline.example.com, http://localhost:5173 ,",
            ["https://careerline.example.com", "http://localhost:5173"],
        ),
    ],
)
def test_cors_origins_come_from_a_comma_separated_env_var(monkeypatch, value, expected):
    monkeypatch.setenv("CORS_ORIGINS", value)
    assert Settings(_env_file=None).CORS_ORIGINS == expected
