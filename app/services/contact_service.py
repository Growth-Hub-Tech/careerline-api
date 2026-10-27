"""The contact form: store the message, email the team and thank the sender (Day 5)."""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.core.logging import get_logger
from app.email.outbox import send_email
from app.models.contact import ContactMessage
from app.schemas.contact import ContactReceipt, ContactRequest

logger = get_logger(__name__)

# Per sender address and per IP address
MESSAGES_PER_HOUR = 5


async def _check_limits(db: AsyncSession, email: str, client_ip: str | None) -> None:
    keys = [rate_limit.bucket("contact:email", email)]
    if client_ip:
        keys.append(rate_limit.bucket("contact:ip", client_ip))
    for key in keys:
        result = await rate_limit.hit(db, key, limit=MESSAGES_PER_HOUR, window_seconds=3600)
        if not result.allowed:
            raise RateLimitedError(
                "Too many messages. Please try again later.",
                headers={"Retry-After": str(result.retry_after)},
            )


async def submit_contact_message(
    db: AsyncSession, data: ContactRequest, client_ip: str | None
) -> ContactReceipt:
    now = datetime.now(UTC)
    if data.website:
        # The spam trap: people never see this field, bots fill it. Answer like a success
        # (so bots learn nothing) but store and send nothing.
        logger.info("contact_spam_dropped")
        return ContactReceipt(ticket_id=f"CT-{now:%Y%m%d}-0000", status="received", received_at=now)

    email = str(data.email).lower()
    await _check_limits(db, email, client_ip)

    # The ticket number is built from the row id, so take the id first
    message_id = (
        await db.execute(text("SELECT nextval(pg_get_serial_sequence('contact_messages', 'id'))"))
    ).scalar_one()
    ticket_id = f"CT-{now:%Y%m%d}-{message_id:04d}"
    db.add(
        ContactMessage(
            id=message_id,
            ticket_id=ticket_id,
            full_name=data.full_name,
            email=email,
            topic=data.topic,
            organisation=data.organisation,
            message=data.message,
            created_at=now,
        )
    )
    context = {
        "ticket_id": ticket_id,
        "full_name": data.full_name,
        "email": email,
        "topic": data.topic,
        "organisation": data.organisation,
        "message": data.message,
        "received_at": f"{now:%d %b %Y, %H:%M} UTC",
    }
    # Both emails go out through jobs, queued in this transaction
    await send_email(
        db,
        to=settings.SUPPORT_EMAIL,
        template="contact_received",
        context=context,
        reply_to=email,
        dedupe_key=f"contact:{ticket_id}:team",
    )
    await send_email(
        db,
        to=email,
        template="contact_acknowledgement",
        context=context,
        reply_to=settings.SUPPORT_EMAIL,
        dedupe_key=f"contact:{ticket_id}:ack",
    )
    logger.info("contact_message_received", ticket_id=ticket_id, topic=data.topic)
    return ContactReceipt(ticket_id=ticket_id, status="received", received_at=now)
