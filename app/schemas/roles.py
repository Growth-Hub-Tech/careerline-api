from typing import Literal

from pydantic import BaseModel

from app.schemas.common import LevelName

Track = Literal["tech", "revenue"]


class RoleSkill(BaseModel):
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
    description: str
    skills: list[RoleSkill]
    test_ids: list[int]
