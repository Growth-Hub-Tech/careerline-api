from datetime import datetime

from pydantic import BaseModel

from app.schemas.attempts import SubskillRef
from app.schemas.common import LevelName


class SkillHistoryEntry(BaseModel):
    attempt_id: int
    skill_id: int
    skill_name: str
    level: LevelName
    score: int
    confidence: float
    strengths: list[SubskillRef]
    weaknesses: list[SubskillRef]
    recorded_at: datetime


class SkillHistory(BaseModel):
    """Every finished test, newest first: how the person's level in each skill moved."""

    learner_id: int
    entries: list[SkillHistoryEntry]
