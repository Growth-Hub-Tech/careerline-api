from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Money

ProviderType = Literal["incubate", "partner"]
Mode = Literal["online", "in_person", "hybrid"]
ClickSource = Literal["result", "beginner_path", "programme_list", "profile"]


class ProgrammeSummary(BaseModel):
    programme_id: int
    name: str
    provider: str
    provider_type: ProviderType
    mode: Mode
    duration_weeks: int
    price: Money


class Programme(ProgrammeSummary):
    summary: str
    skills: list[str]
    role_ids: list[int]
    url: str


class ProgrammeClickRequest(BaseModel):
    source: ClickSource
    result_id: int | None = None


class ProgrammeClick(BaseModel):
    """A recorded click; send the person to redirect_url (it carries the referral code)."""

    click_id: str
    programme_id: int
    redirect_url: str
    clicked_at: datetime
