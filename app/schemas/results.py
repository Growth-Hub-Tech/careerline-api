from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import LevelName

Band = Literal["strong", "developing", "weak"]
ReportStatus = Literal["generating", "ready", "failed"]


class ResultSummary(BaseModel):
    result_id: int
    attempt_id: int
    test_id: int
    skill_id: int
    skill_name: str
    level: LevelName
    percentage_score: float
    passed: bool
    completed_at: datetime


class SubskillScore(BaseModel):
    subskill_id: int
    subskill_name: str
    percentage_score: float
    band: Band


class ResultRecommendation(BaseModel):
    subskill_name: str
    text: str
    programme_id: int | None = None


class ResultDetail(ResultSummary):
    declared_level: LevelName
    percentile: int | None
    subskills: list[SubskillScore]
    strengths: list[str]
    gaps: list[str]
    recommendations: list[ResultRecommendation]


class Report(BaseModel):
    """The PDF report of one result. Poll until status is "ready", then download."""

    result_id: int
    status: ReportStatus
    download_url: str | None
    expires_at: datetime | None
    generated_at: datetime | None
