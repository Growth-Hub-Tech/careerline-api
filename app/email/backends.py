"""Where emails go, chosen by EMAIL_BACKEND (see settings.email_backend).

- smtp: real emails through any SMTP provider (Brevo, Mailgun, SendGrid, Amazon SES, Gmail...)
- test_mailbox: stored in test_mailbox_messages, readable at GET /api/v1/test-mailbox
- console: only logged (development)
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage as MimeMessage
from email.utils import make_msgid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.email.message import EmailMessage
from app.models.email import TestMailboxMessage

logger = get_logger(__name__)


class EmailNotConfigured(Exception):
    """The backend needs settings that are missing (e.g. SMTP_HOST)."""


class EmailBackend(Protocol):
    name: str

    async def send(self, message: EmailMessage, *, session: AsyncSession | None = None) -> None: ...


class ConsoleBackend:
    name = "console"

    async def send(self, message: EmailMessage, *, session: AsyncSession | None = None) -> None:
        # Development only: the text body is logged so links can be clicked from the terminal
        logger.info("email_logged", to=message.to, subject=message.subject, text=message.text)


class TestMailboxBackend:
    name = "test_mailbox"

    async def send(self, message: EmailMessage, *, session: AsyncSession | None = None) -> None:
        if session is None:
            raise EmailNotConfigured("the test mailbox needs a database session")
        session.add(
            TestMailboxMessage(
                to_email=message.to.lower(),
                subject=message.subject,
                html_body=message.html,
                text_body=message.text,
                reply_to=message.reply_to,
            )
        )


class SmtpBackend:
    name = "smtp"

    def build(self, message: EmailMessage) -> MimeMessage:
        mime = MimeMessage()
        mime["From"] = settings.EMAIL_FROM
        mime["To"] = message.to
        mime["Subject"] = message.subject
        if message.reply_to:
            mime["Reply-To"] = message.reply_to
        domain = settings.EMAIL_FROM.rsplit("@", 1)[-1].strip(" >") or None
        mime["Message-ID"] = make_msgid(idstring=message.reference, domain=domain)
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        return mime

    def _send_blocking(self, mime: MimeMessage) -> None:
        security = settings.SMTP_SECURITY.lower()
        timeout = settings.SMTP_TIMEOUT_SECONDS
        context = ssl.create_default_context()
        server: smtplib.SMTP
        if security == "ssl":
            server = smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout, context=context
            )
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(mime)

    async def send(self, message: EmailMessage, *, session: AsyncSession | None = None) -> None:
        if not settings.SMTP_HOST:
            raise EmailNotConfigured("EMAIL_BACKEND is smtp but SMTP_HOST is not set")
        # smtplib blocks: run it in a thread so the API keeps answering meanwhile
        await asyncio.to_thread(self._send_blocking, self.build(message))
        logger.info("email_sent", to=message.to, subject=message.subject)


def get_backend() -> EmailBackend:
    backend = settings.email_backend
    if backend == "smtp":
        return SmtpBackend()
    if backend == "test_mailbox":
        return TestMailboxBackend()
    return ConsoleBackend()
