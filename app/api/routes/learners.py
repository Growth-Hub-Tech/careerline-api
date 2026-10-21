from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db, require_same_learner
from app.core.exceptions import NotFoundError
from app.core.responses import EnvelopeRoute, errors, ok
from app.models.models import Learner, TestAttempt
from app.schemas.learners import BehaviouralAnswersRequest, LearnerRegisterRequest
from app.services.learner_service import (
    get_behavioural_questions,
    register_learner,
    submit_behavioural_answers,
)

#Create a router for learner endpoints
router = APIRouter(prefix="/learners", tags=["Learners"], route_class=EnvelopeRoute)


#REGISTER A NEW LEARNER
@router.post("/register")
async def learner_register(data: LearnerRegisterRequest, db: AsyncSession = Depends(get_db)):
    learner_id = await register_learner(
        db=db,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone
    )
    return ok(
        {"learner_id": learner_id},
        message=f"Learner {data.full_name} registered successfully",
    )


#GET LEARNER PROFILE
#Only your own profile: it holds your email and phone number
@router.get("/{learner_id}", responses=errors(401, 403, 404))
async def get_learner_profile(
    learner_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    require_same_learner(learner_id, current_learner)
    result = await db.execute(
        select(Learner).where(Learner.learner_id == learner_id)
    )
    learner = result.scalar_one_or_none()
    if not learner:
        raise NotFoundError(f"Learner {learner_id} not found")
    return {
        "learner": {
            "learner_id": learner.learner_id,
            "full_name": learner.full_name,
            "email": learner.email,
            "phone_number": learner.phone_number,
            "learner_status": learner.learner_status.value.lower(),
            "registration_date": learner.registration_date
        }
    }


#GET BEHAVIOURAL QUESTIONS FOR A SKILL
@router.get("/behavioural-questions/{skill_id}", responses=errors(404))
async def behavioural_questions(skill_id: int, db: AsyncSession = Depends(get_db)):
    questions = await get_behavioural_questions(db=db, skill_id=skill_id)
    if not questions:
        raise NotFoundError(f"Skill {skill_id} not found")
    return ok(questions, message=f"Behavioural questions retrieved for skill_id={skill_id}")


#SUBMIT BEHAVIOURAL ANSWERS
@router.post("/behavioural-answers", responses=errors(401, 403, 404))
async def behavioural_answers(
    data: BehaviouralAnswersRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    #learner_id stays in the body for old clients, but it must be you
    require_same_learner(data.learner_id, current_learner)

    #...and the attempt must be yours too
    attempt = await db.get(TestAttempt, data.attempt_id)
    if attempt is None:
        raise NotFoundError(f"Attempt {data.attempt_id} not found")
    require_same_learner(attempt.learner_id, current_learner)

    answers = [
        {"question_id": item.question_id, "answer_text": item.answer_text}
        for item in data.answers
    ]
    result = await submit_behavioural_answers(
        db=db,
        learner_id=data.learner_id,
        attempt_id=data.attempt_id,
        answers=answers
    )
    return ok(result, message=f"Behavioural answers saved for learner_id={data.learner_id}")
