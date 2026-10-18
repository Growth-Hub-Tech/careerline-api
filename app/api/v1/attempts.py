from app.core.auth import get_current_learner, require_same_learner
from app.models.models import TestAttempt, Skill, Learner
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.services.attempt_service import start_attempt
from app.services.scoring_service import submit_and_score, generate_recommendations, SubmitError
from app.models.models import TestAttempt, ProficiencyLevel, Skill, AttemptStatus

#Create a router for attempt endpoints
router = APIRouter(prefix="/attempts", tags=["Attempts"])

#DATA MODELS
class StartAttemptRequest(BaseModel):
    skill_id: int
    declared_level: str

class AnswerItem(BaseModel):
    question_id: int
    selected_option_id: int

class SubmitRequest(BaseModel):
    attempt_id: int
    answers: list[AnswerItem]


#START A TEST ATTEMPT
@router.post("/start")
async def start_test_attempt(
    data: StartAttemptRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    try:
        attempt_data = await start_attempt(
            db=db,
            learner_id=current_learner.learner_id,  #from token
            skill_id=data.skill_id,
            declared_level=data.declared_level
        )
        return {
            "status": "Success",
            "attempt_id": attempt_data["attempt_id"],
            "declared_level": attempt_data["declared_level"],
            "total_questions": attempt_data["total_questions"],
            "questions": attempt_data["questions"],
            "message": f"Test attempt started for learner_id={current_learner.learner_id} on skill_id={data.skill_id} at {data.declared_level} level"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#SUBMIT ANSWERS AND GET SCORE
@router.post("/submit")
async def submit_answers(
    data: SubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    try:
        answers = [
            {"question_id": item.question_id, "selected_option_id": item.selected_option_id}
            for item in data.answers
        ]
        final_result = await submit_and_score(
            db=db,
            attempt_id=data.attempt_id,
            learner_id=current_learner.learner_id,  #from token
            answers=answers
        )
        recommendations = await generate_recommendations(
            db=db,
            attempt_id=data.attempt_id,
            learner_id=current_learner.learner_id  #from token
        )
        return {
            "status": "Success",
            "result": final_result,
            "recommendations": recommendations,
            "message": f"Answers submitted and scored for attempt_id={data.attempt_id}"
        }
    except SubmitError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#GET ATTEMPT DETAIL
@router.get("/{attempt_id}")
async def get_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    try:
        result = await db.execute(
            select(TestAttempt).where(TestAttempt.attempt_id == attempt_id)
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise HTTPException(status_code=404, detail=f"Attempt {attempt_id} not found")
        require_same_learner(attempt.learner_id, current_learner)

        return {
            "status": "Success",
            "attempt": {
                "attempt_id": attempt.attempt_id,
                "learner_id": attempt.learner_id,
                "skill_id": attempt.skill_id,
                "attempt_status": attempt.attempt_status.value.lower(),
                "overall_percentage": float(attempt.overall_percentage) if attempt.overall_percentage else None,
                "start_time": attempt.start_time,
                "end_time": attempt.end_time
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#GET ATTEMPT HISTORY FOR A LEARNER
@router.get("/learner/{learner_id}")
async def get_learner_attempts(
    learner_id: int,
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    require_same_learner(learner_id, current_learner)
    try:
        result = await db.execute(
            select(TestAttempt)
            .where(TestAttempt.learner_id == learner_id)
            .order_by(TestAttempt.start_time.desc())
            .offset(offset)
            .limit(limit)
        )
        attempts = result.scalars().all()

        return {
            "status": "Success",
            "learner_id": learner_id,
            "total": len(attempts),
            "attempts": [
                {
                    "attempt_id": a.attempt_id,
                    "skill_id": a.skill_id,
                    "attempt_status": a.attempt_status.value.lower(),
                    "overall_percentage": float(a.overall_percentage) if a.overall_percentage else None,
                    "start_time": a.start_time,
                    "end_time": a.end_time
                }
                for a in attempts
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#CANCEL AN IN-PROGRESS ATTEMPT
@router.patch("/{attempt_id}/cancel")
async def cancel_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    try:
        result = await db.execute(
            select(TestAttempt).where(TestAttempt.attempt_id == attempt_id)
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            raise HTTPException(status_code=404, detail=f"Attempt {attempt_id} not found")

        #Only the learner who owns the attempt can cancel it
        if attempt.learner_id != current_learner.learner_id:
            raise HTTPException(status_code=403, detail=f"Attempt {attempt_id} does not belong to you")

        #Check if already completed
        if attempt.attempt_status != AttemptStatus.IN_PROGRESS:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel attempt that is already {attempt.attempt_status.value.lower()}"
            )

        #Cancel the attempt
        attempt.attempt_status = AttemptStatus.CANCELLED
        return {
            "status": "Success",
            "message": f"Attempt {attempt_id} cancelled successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))