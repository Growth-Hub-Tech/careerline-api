from datetime import datetime

from pydantic import BaseModel, Field


class TestMailboxMessageOut(BaseModel):
    id: int
    to: str
    subject: str
    text: str
    html: str
    reply_to: str | None
    links: list[str] = Field(description="Every link in the email, e.g. a confirm or reset link")
    received_at: datetime


class TestMailbox(BaseModel):
    to: str
    messages: list[TestMailboxMessageOut] = Field(description="Newest first")


class TestMailboxCleared(BaseModel):
    to: str
    deleted: int
