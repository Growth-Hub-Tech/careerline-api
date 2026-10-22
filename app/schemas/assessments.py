# The catalogue of tests a person can take (GET /tests). Taking a test is /attempts.
# Named "assessment" in code so pytest never mistakes these models for test classes.
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import LevelName

AssessmentFormat = Literal["adaptive", "fixed"]
AccessReason = Literal["free", "credits", "subscription", "insufficient_credits"]


class AssessmentSummary(BaseModel):
    test_id: int
    title: str
    skill_id: int
    skill_name: str
    levels: list[LevelName]
    format: AssessmentFormat
    question_count: int
    duration_minutes: int
    price_credits: int  # 0 = free
    role_ids: list[int]


class AssessmentDetail(AssessmentSummary):
    description: str
    subskills: list[str]
    what_you_get: list[str]


class AssessmentAccess(BaseModel):
    """Can the logged-in person start this test now, and if not, what do they need?"""

    test_id: int
    can_start: bool
    reason: AccessReason
    price_credits: int
    credits_balance: int
