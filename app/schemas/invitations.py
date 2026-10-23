# A recruiter invites a candidate (or an organisation a team member) to take a test.
# sent -> accepted (the invitee opens the link and starts) -> completed (test submitted).
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

InvitationKind = Literal["candidate", "team_member"]
InvitationStatus = Literal["sent", "accepted", "completed", "expired", "revoked"]


class InvitationCreate(BaseModel):
    kind: InvitationKind = "candidate"
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    test_id: int
    candidate_id: int | None = None
    organisation_id: int | None = None
    message: str | None = Field(default=None, max_length=1000)
    expires_in_days: int = Field(default=7, ge=1, le=30)


class Invitation(BaseModel):
    """What the sender sees."""

    invitation_id: int
    token: str
    kind: InvitationKind
    status: InvitationStatus
    email: EmailStr
    full_name: str
    test_id: int
    test_title: str
    candidate_id: int | None
    organisation_id: int | None
    attempt_id: int | None
    result_id: int | None
    invite_url: str
    sent_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime


class InvitationPublic(BaseModel):
    """What the invitee sees from the link, before and after logging in."""

    token: str
    status: InvitationStatus
    invited_by: str
    full_name: str
    test_id: int
    test_title: str
    duration_minutes: int
    message: str | None
    expires_at: datetime
    attempt_id: int | None
