# Beginner path (PRD 4.2): an intake on personality, goals, time and money, then ranked career
# paths with reasons, each linked to a matching programme.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.programmes import ProgrammeSummary

IntakeSection = Literal["personality", "goals", "time", "finances"]
QuestionKind = Literal["single_choice", "multi_choice", "scale"]


class IntakeOption(BaseModel):
    value: str
    label: str


class IntakeQuestion(BaseModel):
    question_id: str
    section: IntakeSection
    text: str
    kind: QuestionKind
    options: list[IntakeOption]


class IntakeQuestionnaire(BaseModel):
    version: str
    questions: list[IntakeQuestion]


class IntakeAnswer(BaseModel):
    question_id: str
    values: list[str] = Field(min_length=1)


class IntakeSubmission(BaseModel):
    version: str
    answers: list[IntakeAnswer] = Field(min_length=1)


class CareerPathRecommendation(BaseModel):
    rank: int
    role_id: int
    title: str
    match_score: int = Field(ge=0, le=100)
    reasons: list[str]
    starting_test_id: int | None = Field(
        description="The test to take first (200 + skill_id); null when none of the role's "
        "skills can be tested yet"
    )
    programme: ProgrammeSummary | None = Field(description="null until programmes are real")


class BeginnerPath(BaseModel):
    """The career paths of one intake. No intake yet: intake_id and submitted_at are null and
    recommendations is empty."""

    intake_id: int | None
    submitted_at: datetime | None
    recommendations: list[CareerPathRecommendation]
