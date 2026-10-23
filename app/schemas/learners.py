from pydantic import BaseModel


# A single behavioural answer submitted by the learner
class BehaviouralAnswerItem(BaseModel):
    question_id: int
    answer_text: str


class BehaviouralAnswersRequest(BaseModel):
    learner_id: int
    attempt_id: int
    answers: list[BehaviouralAnswerItem]
