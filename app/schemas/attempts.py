from pydantic import BaseModel


# The learner declares their level before taking the test
class StartAttemptRequest(BaseModel):
    skill_id: int
    declared_level: str  # BEGINNER, JUNIOR, MID or ADVANCED


# A single answer submitted by the learner
class AnswerItem(BaseModel):
    question_id: int
    selected_option_id: int


class SubmitRequest(BaseModel):
    attempt_id: int
    answers: list[AnswerItem]
