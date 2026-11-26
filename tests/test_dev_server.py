"""python -m app (the local development server) serves on PORT from the environment or .env."""

import pytest
from pydantic import ValidationError

from app import __main__ as dev_server
from app.core.config import Settings


def _settings(env_file=None, **values) -> Settings:
    return Settings(_env_file=env_file, DATABASE_URL="postgresql://x/y", SECRET_KEY="k", **values)


@pytest.fixture(autouse=True)
def _no_port_in_the_shell(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)


def test_the_port_defaults_to_8000():
    assert _settings().PORT == 8000


def test_the_port_is_read_from_the_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8012\n")
    assert _settings(env_file=env_file).PORT == 8012


def test_the_shell_overrides_the_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=8012\n")
    monkeypatch.setenv("PORT", "8013")
    assert _settings(env_file=env_file).PORT == 8013


@pytest.mark.parametrize("port", ["0", "65536", "eight"])
def test_an_impossible_port_is_refused(monkeypatch, port):
    monkeypatch.setenv("PORT", port)
    with pytest.raises(ValidationError):
        _settings()


def test_the_dev_server_serves_on_the_configured_port(monkeypatch):
    calls = []
    monkeypatch.setattr(dev_server.settings, "PORT", 8014)
    monkeypatch.setattr(dev_server.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    dev_server.main()
    assert calls == [(("app.main:app",), {"port": 8014, "reload": True})]
