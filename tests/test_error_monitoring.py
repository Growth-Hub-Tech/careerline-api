"""Errors reach Sentry when SENTRY_DSN is set, without passwords, bodies or local variables."""

import sentry_sdk

from app.core import logging as app_logging
from app.core.config import settings


def _record(monkeypatch, name: str) -> list:
    calls: list = []
    monkeypatch.setattr(sentry_sdk, name, lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_without_a_dsn_nothing_is_sent(monkeypatch):
    calls = _record(monkeypatch, "init")
    monkeypatch.setattr(settings, "SENTRY_DSN", "")
    app_logging.init_error_monitoring()
    assert calls == []


def test_with_a_dsn_sentry_starts_without_personal_data(monkeypatch):
    calls = _record(monkeypatch, "init")
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://public@o1.ingest.sentry.io/1")
    monkeypatch.setattr(settings, "APP_ENV", "production")
    app_logging.init_error_monitoring()
    ((_, options),) = calls
    assert options["dsn"] == "https://public@o1.ingest.sentry.io/1"
    assert options["environment"] == "production"
    assert options["send_default_pii"] is False
    assert options["max_request_body_size"] == "never"
    assert options["include_local_variables"] is False


def _sentry_on(monkeypatch) -> tuple[list, list]:
    monkeypatch.setattr(sentry_sdk, "is_initialized", lambda: True)
    return _record(monkeypatch, "capture_exception"), _record(monkeypatch, "capture_message")


def test_an_error_with_an_exception_is_sent_as_that_exception(monkeypatch):
    exceptions, messages = _sentry_on(monkeypatch)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        app_logging.report_errors_to_sentry(
            None, "exception", {"event": "unhandled_error", "exc_info": True, "path": "/x"}
        )
    assert len(exceptions) == 1 and messages == []


def test_an_error_without_an_exception_is_sent_under_its_event_name(monkeypatch):
    exceptions, messages = _sentry_on(monkeypatch)
    app_logging.report_errors_to_sentry(None, "error", {"event": "job_dead", "job_id": 7})
    assert exceptions == []
    assert messages == [(("job_dead",), {"level": "error"})]


def test_lines_below_error_are_not_sent(monkeypatch):
    exceptions, messages = _sentry_on(monkeypatch)
    for level in ("debug", "info", "warning"):
        app_logging.report_errors_to_sentry(None, level, {"event": "job_succeeded"})
    assert exceptions == [] and messages == []


def test_nothing_is_sent_while_sentry_is_off(monkeypatch):
    monkeypatch.setattr(sentry_sdk, "is_initialized", lambda: False)
    exceptions = _record(monkeypatch, "capture_exception")
    messages = _record(monkeypatch, "capture_message")
    app_logging.report_errors_to_sentry(None, "error", {"event": "job_dead"})
    assert exceptions == [] and messages == []


def test_an_error_log_line_goes_through_the_processor(monkeypatch):
    exceptions, _ = _sentry_on(monkeypatch)
    app_logging.configure_logging()
    try:
        raise ValueError("job crashed")
    except ValueError:
        app_logging.get_logger("app.jobs").exception("job_failed", job_id=3)
    assert len(exceptions) == 1
