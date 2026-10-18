from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.responses import errors
from app.core.auth import get_current_learner, require_same_learner
from app.services.learner_service import (
    register_learner, get_behavioural_questions,
    submit_behavioural_answers
)
from app.models.models import Learner, TestAttempt
from sqlalchemy import select

#Create a router for learner endpoints
router = APIRouter(prefix="/learners", tags=["Learners"])

#DATA MODELS
class RegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str

class BehaviouralAnswerItem(BaseModel):
    question_id: int
    answer_text: str

class BehaviouralAnswersRequest(BaseModel):
    learner_id: int
    attempt_id: int
    answers: list[BehaviouralAnswerItem]


#REGISTER A NEW LEARNER
@router.post("/register")
async def learner_register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        learner_id = await register_learner(
            db=db,
            full_name=data.full_name,
            email=data.email,
            phone=data.phone
        )
        return {
            "status": "Success",
            "learner_id": learner_id,
            "message": f"Learner {data.full_name} registered successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#GET LEARNER PROFILE
#Only your own profile: it holds your email and phone number
@router.get("/{learner_id}", responses=errors(401, 403, 404))
async def get_learner_profile(
    learner_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    require_same_learner(learner_id, current_learner)
    try:
        result = await db.execute(
            select(Learner).where(Learner.learner_id == learner_id)
        )
        learner = result.scalar_one_or_none()
        if not learner:
            raise HTTPException(status_code=404, detail=f"Learner {learner_id} not found")
        return {
            "status": "Success",
            "learner": {
                "learner_id": learner.learner_id,
                "full_name": learner.full_name,
                "email": learner.email,
                "phone_number": learner.phone_number,
                "learner_status": learner.learner_status.value.lower(),
                "registration_date": learner.registration_date
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#GET BEHAVIOURAL QUESTIONS FOR A SKILL
@router.get("/behavioural-questions/{skill_id}", responses=errors(404))
async def behavioural_questions(skill_id: int, db: AsyncSession = Depends(get_db)):
    try:
        questions = await get_behavioural_questions(db=db, skill_id=skill_id)
        if not questions:
            raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")
        return {
            "status": "Success",
            "data": questions,
            "message": f"Behavioural questions retrieved for skill_id={skill_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=404, detail=f"Attempt {data.attempt_id} not found")
    require_same_learner(attempt.learner_id, current_learner)
    try:
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
        return {
            "status": "Success",
            "result": result,
            "message": f"Behavioural answers saved for learner_id={data.learner_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))