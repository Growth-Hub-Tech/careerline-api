from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db, require_same_learner
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError
from app.core.responses import EnvelopeRoute, errors, ok
from app.models.models import AttemptStatus, Learner, TestAttempt
from app.schemas.attempts import StartAttemptRequest, SubmitRequest
from app.services.attempt_service import start_attempt
from app.services.scoring_service import generate_recommendations, submit_and_score

#Create a router for attempt endpoints
router = APIRouter(prefix="/attempts", tags=["Attempts"], route_class=EnvelopeRoute)


#Percentage for scored attempts only, so a real 0% shows as 0.
#(The column defaults to 0 while an attempt is in progress, so those stay null.)
SCORED_STATUSES = (AttemptStatus.PASSED, AttemptStatus.FAILED, AttemptStatus.COMPLETED)

def score_or_none(attempt):
    if attempt.attempt_status in SCORED_STATUSES and attempt.overall_percentage is not None:
        return float(attempt.overall_percentage)
    return None


#START A TEST ATTEMPT
@router.post("/start", responses=errors(400, 401))
async def start_test_attempt(
    data: StartAttemptRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    attempt_data = await start_attempt(
        db=db,
        learner_id=current_learner.learner_id,  #from token
        skill_id=data.skill_id,
        declared_level=data.declared_level
    )
    return ok(
        {
            "attempt_id": attempt_data["attempt_id"],
            "declared_level": attempt_data["declared_level"],
            "total_questions": attempt_data["total_questions"],
            "questions": attempt_data["questions"],
        },
        message=f"Test attempt started for learner_id={current_learner.learner_id} on skill_id={data.skill_id} at {data.declared_level} level",
    )

#SUBMIT ANSWERS AND GET SCORE
@router.post("/submit", responses=errors(400, 401, 403, 404, 409))
async def submit_answers(
    data: SubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
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
    return ok(
        {"result": final_result, "recommendations": recommendations},
        message=f"Answers submitted and scored for attempt_id={data.attempt_id}",
    )


#GET ATTEMPT DETAIL
@router.get("/{attempt_id}", responses=errors(401, 403, 404))
async def get_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    result = await db.execute(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise NotFoundError(f"Attempt {attempt_id} not found")
    require_same_learner(attempt.learner_id, current_learner)

    return {
        "attempt": {
            "attempt_id": attempt.attempt_id,
            "learner_id": attempt.learner_id,
            "skill_id": attempt.skill_id,
            "attempt_status": attempt.attempt_status.value.lower(),
            "overall_percentage": score_or_none(attempt),
            "start_time": attempt.start_time,
            "end_time": attempt.end_time
        }
    }


#GET ATTEMPT HISTORY FOR A LEARNER
@router.get("/learner/{learner_id}", responses=errors(401, 403))
async def get_learner_attempts(
    learner_id: int,
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    require_same_learner(learner_id, current_learner)
    result = await db.execute(
        select(TestAttempt)
        .where(TestAttempt.learner_id == learner_id)
        .order_by(TestAttempt.start_time.desc())
        .offset(offset)
        .limit(limit)
    )
    attempts = result.scalars().all()

    return {
        "learner_id": learner_id,
        "total": len(attempts),
        "attempts": [
            {
                "attempt_id": a.attempt_id,
                "skill_id": a.skill_id,
                "attempt_status": a.attempt_status.value.lower(),
                "overall_percentage": score_or_none(a),
                "start_time": a.start_time,
                "end_time": a.end_time
            }
            for a in attempts
        ]
    }


#CANCEL AN IN-PROGRESS ATTEMPT
@router.patch("/{attempt_id}/cancel", responses=errors(400, 401, 403, 404))
async def cancel_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    result = await db.execute(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id)
    )
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise NotFoundError(f"Attempt {attempt_id} not found")

    #Only the learner who owns the attempt can cancel it
    if attempt.learner_id != current_learner.learner_id:
        raise ForbiddenError(f"Attempt {attempt_id} does not belong to you")

    #Check if already completed
    if attempt.attempt_status != AttemptStatus.IN_PROGRESS:
        raise BadRequestError(
            f"Cannot cancel attempt that is already {attempt.attempt_status.value.lower()}"
        )

    #Cancel the attempt
    attempt.attempt_status = AttemptStatus.CANCELLED
    return ok(message=f"Attempt {attempt_id} cancelled successfully")
