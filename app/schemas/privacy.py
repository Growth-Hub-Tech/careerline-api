# Privacy (NDPR / GDPR): consents, a copy of my data, and deleting my account
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConsentKey = Literal["marketing_emails", "share_profile_with_recruiters", "product_research"]
ExportStatus = Literal["queued", "ready", "expired"]


class Consent(BaseModel):
    key: ConsentKey
    granted: bool
    updated_at: datetime


class Consents(BaseModel):
    items: list[Consent]


class ConsentChange(BaseModel):
    key: ConsentKey
    granted: bool


class ConsentUpdate(BaseModel):
    items: list[ConsentChange] = Field(min_length=1)


class DataExport(BaseModel):
    """A copy of everything we hold about me. Poll until "ready", then download (link expires)."""

    export_id: int
    status: ExportStatus
    requested_at: datetime
    download_url: str | None
    expires_at: datetime | None


class AccountDeletionRequest(BaseModel):
    password: str
    reason: str | None = Field(default=None, max_length=500)


class AccountDeletion(BaseModel):
    """Deletion waits 30 days so it can be cancelled, then everything is erased."""

    status: Literal["scheduled", "cancelled"]
    requested_at: datetime
    scheduled_for: datetime | None
