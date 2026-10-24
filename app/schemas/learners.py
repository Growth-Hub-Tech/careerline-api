from pydantic import BaseModel, Field


# A single behavioural answer submitted by the learner
class BehaviouralAnswerItem(BaseModel):
    question_id: int
    answer_text: str


class BehaviouralAnswersRequest(BaseModel):
    learner_id: int | None = Field(
        default=None,
        json_schema_extra={"deprecated": True},
        description="Not needed: the learner is the one signed in. If sent, it must be yours.",
    )
    attempt_id: int
    answers: list[BehaviouralAnswerItem]
