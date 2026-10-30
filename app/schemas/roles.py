from typing import Literal

from pydantic import BaseModel

from app.schemas.common import LevelName

Track = Literal["tech", "revenue"]


class RoleSkill(BaseModel):
    """target_level: the level the role needs in this skill at the mid title (see /job-titles)."""

    skill_id: int
    skill_name: str
    target_level: LevelName


class RoleSummary(BaseModel):
    role_id: int
    title: str
    slug: str
    track: Track
    summary: str


class Role(RoleSummary):
    """skills: the main skill first. test_ids: the tests to take for this role, only for skills
    that can be tested now; until GET /tests is real a test id is 200 + skill_id."""

    description: str
    skills: list[RoleSkill]
    test_ids: list[int]


class JobTitleItem(BaseModel):
    """One step of the job-title ladder and the level expected at it."""

    title_id: int
    slug: str
    name: str
    rank: int
    expected_level: LevelName
    description: str


class JobTitleList(BaseModel):
    items: list[JobTitleItem]
