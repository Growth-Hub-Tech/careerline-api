from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import LevelName

CandidateStatus = Literal["added", "invited", "in_progress", "completed"]
Fit = Literal["strong_fit", "possible_fit", "not_a_fit"]


class CandidateTestResult(BaseModel):
    test_id: int
    test_title: str
    level: LevelName
    percentage_score: float
    passed: bool
    completed_at: datetime
    result_id: int
    # Day 31: whether the result is shared with the organisation (true for every listed result today)
    shared: bool


class Candidate(BaseModel):
    candidate_id: int
    full_name: str
    email: EmailStr
    role_id: int | None
    role_title: str | None
    status: CandidateStatus
    added_at: datetime
    latest_result: CandidateTestResult | None


class CandidateCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    role_id: int | None = None


class CandidateReport(BaseModel):
    """The scored report a recruiter gets once the candidate has finished (PRD 6.3)."""

    candidate_id: int
    full_name: str
    role_title: str | None
    fit: Fit
    summary: str
    results: list[CandidateTestResult]
    # the newest result's PDF (a link that works for a few minutes); null while it is being made
    report_url: str | None
