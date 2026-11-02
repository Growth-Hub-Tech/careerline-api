from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import LevelName

Budget = Literal["free_only", "under_50k", "50k_to_200k", "over_200k"]
Visibility = Literal["private", "recruiters"]
Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Profile(BaseModel):
    learner_id: int
    full_name: str
    headline: str | None
    location: str | None
    current_role: str | None
    years_experience: int | None
    goals: list[str]
    weekly_hours: int | None
    budget: Budget | None
    linkedin_url: str | None
    visibility: Visibility
    completeness: int = Field(ge=0, le=100, description="How complete the profile is, in percent")
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Send only the fields to change."""

    headline: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=120)
    current_role: str | None = Field(default=None, max_length=120)
    years_experience: int | None = Field(default=None, ge=0, le=60)
    goals: list[Goal] | None = Field(default=None, max_length=10)
    weekly_hours: int | None = Field(default=None, ge=0, le=80)
    budget: Budget | None = None
    linkedin_url: str | None = Field(
        default=None, max_length=300, description="https://www.linkedin.com/... (400 otherwise)"
    )
    visibility: Visibility | None = Field(
        default=None,
        description="recruiters: the share_profile_with_recruiters consent is turned on",
    )


class SkillLevel(BaseModel):
    skill_id: int
    skill_name: str
    level: LevelName
    percentage_score: float
    confirmed_at: datetime


class SkillProfile(BaseModel):
    """One skill profile per person: the confirmed level for each skill tested."""

    learner_id: int
    skills: list[SkillLevel]
