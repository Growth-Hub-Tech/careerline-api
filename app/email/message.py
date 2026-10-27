from dataclasses import dataclass


@dataclass(frozen=True)
class EmailMessage:
    """One rendered email, ready for a backend."""

    to: str
    subject: str
    html: str
    text: str
    reply_to: str | None = None
    # Our own id for this email (e.g. "outbox-42"), used as the Message-ID so a resend is
    # recognisable as the same message
    reference: str | None = None
