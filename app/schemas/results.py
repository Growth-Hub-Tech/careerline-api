from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import LevelName

Band = Literal["strong", "developing", "weak"]
ReportStatus = Literal["generating", "ready", "failed"]


class ResultSummary(BaseModel):
    """A finished test (Day 12: real; result_id is the attempt_id). No pass or fail."""

    result_id: int
    attempt_id: int
    test_id: int = Field(description="200 + skill_id, as in GET /roles")
    skill_id: int
    skill_name: str
    level: LevelName
    percentage_score: float
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


class PreviousResult(BaseModel):
    """The person's result in the same skill just before this one (Day 24, pre/post re-test)."""

    result_id: int
    level: LevelName
    percentage_score: float
    completed_at: datetime


class ResultDetail(ResultSummary):
    confidence: float = Field(ge=0, le=1, description="0-1: how sure the level is")
    confidence_label: Literal["low", "medium", "high"]
    percentile: int | None = Field(
        description="Share of all results of this skill (in %) with a lower score; null until "
        "the skill has enough results to compare"
    )
    subskills: list[SubskillScore]
    strengths: list[str]
    gaps: list[str]
    recommendations: list[ResultRecommendation]
    previous_result: PreviousResult | None = Field(
        default=None, description="Day 24: the result in the same skill just before this one"
    )
    score_delta: float | None = Field(
        default=None,
        description="Day 24: percentage_score minus the previous result's (null without one)",
    )


class Report(BaseModel):
    """The PDF report of one result. Poll until status is "ready", then download."""

    result_id: int
    status: ReportStatus
    download_url: str | None
    expires_at: datetime | None
    generated_at: datetime | None
