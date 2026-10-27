"""send_email: the one way to send an email, and the job that delivers it."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.email import backends
from app.email.message import EmailMessage
from app.email.templates import render_email
from app.jobs.queue import enqueue
from app.jobs.registry import PermanentJobError, job
from app.models.email import EmailOutbox

logger = get_logger(__name__)

JOB_KIND = "send_email"


async def send_email(
    db: AsyncSession,
    *,
    to: str,
    template: str,
    context: dict[str, Any],
    reply_to: str | None = None,
    dedupe_key: str | None = None,
) -> int:
    """Render the email now and queue it, in the caller's transaction. Returns its outbox id.

    The same dedupe_key (e.g. "contact:CT-...:ack") never queues a second email.
    """
    if dedupe_key:
        existing = await db.scalar(
            select(EmailOutbox.id).where(EmailOutbox.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return int(existing)
    rendered = render_email(template, context)
    outbox = EmailOutbox(
        to_email=to,
        template=template,
        subject=rendered.subject,
        html_body=rendered.html,
        text_body=rendered.text,
        reply_to=reply_to,
        dedupe_key=dedupe_key,
    )
    db.add(outbox)
    await db.flush()
    await enqueue(db, JOB_KIND, {"outbox_id": outbox.id}, dedupe_key=f"email:{outbox.id}")
    logger.info("email_queued", outbox_id=outbox.id, template=template)
    return outbox.id


@job(JOB_KIND)
async def deliver_email(session: AsyncSession, payload: dict[str, Any]) -> None:
    outbox = await session.scalar(
        select(EmailOutbox).where(EmailOutbox.id == int(payload["outbox_id"])).with_for_update()
    )
    if outbox is None:
        raise PermanentJobError(f"email {payload['outbox_id']} does not exist")
    if outbox.status == "sent":
        return  # already delivered by an earlier run of this job
    if outbox.html_body is None or outbox.text_body is None:
        raise PermanentJobError(f"email {outbox.id} has no body")
    backend = backends.get_backend()
    await backend.send(
        EmailMessage(
            to=outbox.to_email,
            subject=outbox.subject,
            html=outbox.html_body,
            text=outbox.text_body,
            reply_to=outbox.reply_to,
            reference=f"outbox-{outbox.id}",
        ),
        session=session,
    )
    outbox.status = "sent"
    outbox.backend = backend.name
    outbox.sent_at = datetime.now(UTC)
    outbox.html_body = None
    outbox.text_body = None
    logger.info("email_delivered", outbox_id=outbox.id, backend=backend.name)
