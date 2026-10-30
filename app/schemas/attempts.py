from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import LevelName


class StartAttemptRequest(BaseModel):
    skill_id: int
    declared_level: str | None = Field(
        default=None,
        deprecated=True,
        description="Retired (Day 10): ignored. The test finds the level itself.",
    )


class AnswerRequest(BaseModel):
    question_id: int
    selected_option_id: int


class ServedOption(BaseModel):
    option_id: int
    option_text: str


class ServedQuestion(BaseModel):
    """The question to answer now. Never carries the answer."""

    position: int = Field(description="1 for the first question")
    question_id: int
    question_text: str
    subskill_id: int
    options: list[ServedOption]


class SubskillRef(BaseModel):
    subskill_id: int
    subskill_name: str


class SubskillOutcome(SubskillRef):
    answered: int
    correct: int
    percentage_score: float
    band: Literal["strong", "developing", "weak"]


class AttemptResult(BaseModel):
    """The result of a finished test. No pass or fail: a score, a level and how sure we are."""

    score: int = Field(ge=0, le=100)
    level: LevelName
    confidence: float = Field(ge=0, le=1, description="0-1: how sure the level is")
    confidence_label: Literal["low", "medium", "high"]
    answered: int
    correct: int
    strengths: list[SubskillRef]
    weaknesses: list[SubskillRef]
    subskills: list[SubskillOutcome]
    ended_by: Literal["finished", "time_up"]
    completed_at: datetime


class AttemptState(BaseModel):
    """Where a test stands. status in_progress: answer `question`; completed: see `result`;
    expired: the time ran out before enough answers for a result."""

    attempt_id: int
    skill_id: int
    status: Literal["in_progress", "completed", "expired", "cancelled"]
    resumed: bool = False
    total_questions: int
    answered: int
    expires_at: datetime | None
    question: ServedQuestion | None = None
    result: AttemptResult | None = None
    recommendations: dict | None = Field(
        default=None, description="Only in the answer that finishes the test"
    )


# The old fixed test (retired on Day 10): POST /attempts/submit answers 410
class AnswerItem(BaseModel):
    question_id: int
    selected_option_id: int


class SubmitRequest(BaseModel):
    attempt_id: int
    answers: list[AnswerItem]
