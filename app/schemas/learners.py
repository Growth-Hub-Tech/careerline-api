from pydantic import BaseModel


class LearnerRegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str


#A single behavioural answer submitted by the learner
class BehaviouralAnswerItem(BaseModel):
    question_id: int
    answer_text: str


class BehaviouralAnswersRequest(BaseModel):
    learner_id: int
    attempt_id: int
    answers: list[BehaviouralAnswerItem]
