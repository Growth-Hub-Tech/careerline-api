from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

ContactTopic = Literal["general", "support", "sales", "partnership", "organisation_audit"]


class ContactRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    topic: ContactTopic = "general"
    organisation: str | None = Field(default=None, max_length=160)
    message: str = Field(min_length=10, max_length=5000)


class ContactReceipt(BaseModel):
    ticket_id: str
    status: Literal["received"]
    received_at: datetime
