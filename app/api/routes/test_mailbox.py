"""The test mailbox (test server only): read the emails the API "sent", to test sign-up,
password reset and the contact form end to end without a real inbox.

Emails land here when EMAIL_BACKEND=test_mailbox (the default when APP_ENV=staging). Never
mounted in production; answers 404 when emails really go out; asks for X-Test-Mailbox-Token
when TEST_MAILBOX_TOKEN is set.
"""

import re
import secrets

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.responses import EnvelopeRoute, errors
from app.db.session import get_db
from app.models.email import TestMailboxMessage
from app.schemas.test_mailbox import TestMailbox, TestMailboxCleared, TestMailboxMessageOut

# Any address the API may have written to (also test-only domains like .local or .test)
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+$"
_LINK = re.compile(r"https?://[^\s<>\"\')]+")


async def mailbox_guard(
    x_test_mailbox_token: str | None = Header(default=None, include_in_schema=False),
) -> None:
    if not settings.test_mailbox_enabled:
        raise NotFoundError("Not found")
    expected = settings.TEST_MAILBOX_TOKEN
    if expected and not secrets.compare_digest(x_test_mailbox_token or "", expected):
        raise UnauthorizedError("Send the test mailbox token in X-Test-Mailbox-Token")


router = APIRouter(
    prefix="/test-mailbox",
    tags=["Test mailbox (test server only)"],
    route_class=EnvelopeRoute,
    dependencies=[Depends(mailbox_guard)],
)


def _links(text: str) -> list[str]:
    found: list[str] = []
    for link in _LINK.findall(text):
        link = link.rstrip(".,;:!?")
        if link not in found:
            found.append(link)
    return found


@router.get(
    "",
    response_model=TestMailbox,
    responses=errors(401, 404),
    description="The emails sent to one address on the test server, newest first. "
    "Send X-Test-Mailbox-Token when the server has one.",
)
async def read_test_mailbox(
    to: str = Query(
        max_length=320, pattern=EMAIL_PATTERN, description="The address the emails were sent to"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    address = str(to).lower()
    rows = (
        await db.scalars(
            select(TestMailboxMessage)
            .where(TestMailboxMessage.to_email == address)
            .order_by(TestMailboxMessage.id.desc())
            .limit(limit)
        )
    ).all()
    return TestMailbox(
        to=address,
        messages=[
            TestMailboxMessageOut(
                id=row.id,
                to=row.to_email,
                subject=row.subject,
                text=row.text_body,
                html=row.html_body,
                reply_to=row.reply_to,
                links=_links(row.text_body),
                received_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.delete(
    "",
    response_model=TestMailboxCleared,
    responses=errors(401, 404),
    description="Delete the emails sent to one address (start a test with an empty mailbox).",
)
async def clear_test_mailbox(
    to: str = Query(max_length=320, pattern=EMAIL_PATTERN, description="The address to clear"),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    address = str(to).lower()
    result = await db.execute(
        delete(TestMailboxMessage).where(TestMailboxMessage.to_email == address)
    )
    return TestMailboxCleared(to=address, deleted=result.rowcount)  # type: ignore[attr-defined]
