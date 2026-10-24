"""Day 5: every email goes through one interface and one layout.

The layout (app/email/templates/layout.html + layout.txt) is the only file that decides how an
email looks; each email only fills its content. Omotoke's design replaces those two files.
"""

import re
import smtplib
from email.message import EmailMessage as MimeMessage

import pytest

from app.core.config import Settings, settings
from app.email import backends
from app.email.message import EmailMessage
from app.email.templates import TEMPLATE_DIR, available_emails, render_email

SAMPLE_CONTEXT = {
    "ticket_id": "CT-20261027-0001",
    "full_name": "Ada <script>alert(1)</script>",
    "email": "ada@example.com",
    "topic": "support",
    "organisation": "Acme",
    "message": "Hello\nI need help <b>now</b>",
    "received_at": "27 Oct 2026, 10:00 UTC",
}


def test_the_day_5_emails_exist():
    assert {"contact_received", "contact_acknowledgement"} <= set(available_emails())


@pytest.mark.parametrize("name", sorted(available_emails()))
def test_every_email_renders_with_the_one_layout(name):
    rendered = render_email(name, SAMPLE_CONTEXT)
    assert rendered.subject and "{{" not in rendered.subject
    # HTML part: the shared layout, inline styles, brand name, no unrendered placeholders
    assert 'data-layout="careerline-base"' in rendered.html
    assert settings.EMAIL_BRAND_NAME in rendered.html
    assert "style=" in rendered.html
    assert "{{" not in rendered.html and "{%" not in rendered.html
    # Plain-text part: the shared text layout, no HTML tags
    assert settings.EMAIL_BRAND_NAME in rendered.text
    assert not re.search(r"<[a-z/][^>]*>", rendered.text)
    assert "{{" not in rendered.text


def test_what_people_type_is_escaped_in_the_html():
    rendered = render_email("contact_received", SAMPLE_CONTEXT)
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_every_email_template_extends_the_layout():
    for path in TEMPLATE_DIR.glob("emails/*.html"):
        assert '{% extends "layout.html" %}' in path.read_text(), path.name
    for path in TEMPLATE_DIR.glob("emails/*.txt"):
        assert '{% extends "layout.txt" %}' in path.read_text(), path.name


@pytest.mark.parametrize(
    ("env", "backend"),
    [
        ("production", "smtp"),
        ("staging", "test_mailbox"),
        ("development", "console"),
        ("test", "console"),
    ],
)
def test_the_default_backend_depends_on_the_environment(env, backend, monkeypatch):
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)
    assert (
        Settings(DATABASE_URL="postgresql://x/y", SECRET_KEY="k", APP_ENV=env).email_backend
        == backend
    )


def test_email_backend_can_be_chosen(monkeypatch):
    s = Settings(
        DATABASE_URL="postgresql://x/y", SECRET_KEY="k", APP_ENV="staging", EMAIL_BACKEND="smtp"
    )
    assert s.email_backend == "smtp"


def test_an_unknown_backend_is_refused():
    with pytest.raises(ValueError):
        Settings(DATABASE_URL="postgresql://x/y", SECRET_KEY="k", EMAIL_BACKEND="pigeon")


def _message() -> EmailMessage:
    rendered = render_email("contact_acknowledgement", SAMPLE_CONTEXT)
    return EmailMessage(
        to="ada@example.com",
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        reply_to="support@example.com",
        reference="outbox-1",
    )


async def test_smtp_sends_one_message_with_a_text_and_an_html_part(monkeypatch):
    sent: list[MimeMessage] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host, self.port = host, port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            self.tls = True

        def login(self, username, password):
            self.user = username

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "not-a-real-password")
    await backends.SmtpBackend().send(_message())

    (mime,) = sent
    assert mime["To"] == "ada@example.com"
    assert mime["Reply-To"] == "support@example.com"
    assert mime["From"] == settings.EMAIL_FROM
    assert mime["Message-ID"]
    kinds = [part.get_content_type() for part in mime.walk()]
    assert "text/plain" in kinds and "text/html" in kinds


async def test_smtp_without_a_host_fails_loudly(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    with pytest.raises(backends.EmailNotConfigured):
        await backends.SmtpBackend().send(_message())


async def test_the_console_backend_only_logs(caplog):
    await backends.ConsoleBackend().send(_message())
