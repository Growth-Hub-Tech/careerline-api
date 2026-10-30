from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db, require_same_learner
from app.core.exceptions import BadRequestError, ForbiddenError, GoneError, NotFoundError
from app.core.responses import EnvelopeRoute, errors, ok
from app.models.models import AttemptStatus, Learner, TestAttempt
from app.schemas.attempts import AnswerRequest, AttemptState, StartAttemptRequest, SubmitRequest
from app.services.test_taking_service import (
    answer_question,
    attempt_result,
    current_state,
)
from app.services.test_taking_service import start_or_resume as start_attempt

# Create a router for attempt endpoints
router = APIRouter(prefix="/attempts", tags=["Attempts"], route_class=EnvelopeRoute)


# Percentage for scored attempts only, so a real 0% shows as 0.
# (The column defaults to 0 while an attempt is in progress, so those stay null.)
SCORED_STATUSES = (AttemptStatus.PASSED, AttemptStatus.FAILED, AttemptStatus.COMPLETED)


def score_or_none(attempt):
    if attempt.attempt_status in SCORED_STATUSES and attempt.overall_percentage is not None:
        return float(attempt.overall_percentage)
    return None


# START (OR RESUME) A TEST: the adaptive test of Day 10, one question at a time
@router.post(
    "/start",
    response_model=AttemptState,
    responses=errors(401, 404, 409),
    description="Starts the adaptive test of a skill and returns its first question, or resumes "
    "the test already in progress for that skill (resumed: true, the same question). 16 "
    "questions, harder after a right answer and easier after a wrong one; 30 minutes. "
    "declared_level is retired and ignored. 409 skill_not_ready: the skill cannot be tested yet.",
)
async def start_test_attempt(
    data: StartAttemptRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await start_attempt(db, current_learner.learner_id, data.skill_id)  # from token


# THE QUESTION TO ANSWER NOW (resume after a reload)
@router.get(
    "/{attempt_id}/question",
    response_model=AttemptState,
    responses=errors(401, 403, 404),
    description="Where the test stands: the question to answer now (status in_progress), the "
    "result (completed), or expired (the time ran out before enough answers for a result).",
)
async def get_current_question(
    attempt_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await current_state(db, attempt_id, current_learner.learner_id)


# ANSWER THE CURRENT QUESTION: the answer to it is never sent back
@router.post(
    "/{attempt_id}/answer",
    response_model=AttemptState,
    responses=errors(400, 401, 403, 404, 409, 410),
    description="Answers the question to answer now and returns the next one, or, after the "
    "last question, the result (status completed, with result and recommendations). 409 "
    "not_current_question: that question is not the one to answer now (already answered, or "
    "never served); 409 attempt_finished: the test is over; 410 expired: the time ran out "
    "(details.status says whether it was scored: completed, or expired).",
)
async def answer_current_question(
    attempt_id: int,
    data: AnswerRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await answer_question(
        db, attempt_id, current_learner.learner_id, data.question_id, data.selected_option_id
    )


# THE OLD FIXED PASS/FAIL TEST: retired on Day 10
@router.post("/submit", responses=errors(410), deprecated=True)
async def submit_answers(data: SubmitRequest):
    raise GoneError(
        "The fixed pass/fail test is retired: answer one question at a time with "
        "POST /attempts/{attempt_id}/answer"
    )


# GET ATTEMPT DETAIL
# MY ATTEMPT HISTORY: the learner comes from the session (Day 7)
@router.get("/me", responses=errors(401))
async def get_my_attempts(
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await get_learner_attempts(
        current_learner.learner_id, limit, offset, db, current_learner
    )


@router.get("/{attempt_id}", responses=errors(401, 403, 404))
async def get_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    result = await db.execute(select(TestAttempt).where(TestAttempt.attempt_id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise NotFoundError(f"Attempt {attempt_id} not found")
    require_same_learner(attempt.learner_id, current_learner)
    attempt_outcome = await attempt_result(db, attempt)

    return {
        "attempt": {
            "attempt_id": attempt.attempt_id,
            "learner_id": attempt.learner_id,
            "skill_id": attempt.skill_id,
            "attempt_status": attempt.attempt_status.value.lower(),
            "overall_percentage": score_or_none(attempt),
            "start_time": attempt.start_time,
            "end_time": attempt.end_time,
            # Day 10: the result of a finished adaptive test (null otherwise)
            "result": attempt_outcome.model_dump(mode="json") if attempt_outcome else None,
        }
    }


# GET ATTEMPT HISTORY FOR A LEARNER
# (deprecated: use /attempts/me)
@router.get("/learner/{learner_id}", responses=errors(401, 403), deprecated=True)
async def get_learner_attempts(
    learner_id: int,
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
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
                "end_time": a.end_time,
            }
            for a in attempts
        ],
    }


# CANCEL AN IN-PROGRESS ATTEMPT
@router.patch("/{attempt_id}/cancel", responses=errors(400, 401, 403, 404))
async def cancel_attempt(
    attempt_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    result = await db.execute(select(TestAttempt).where(TestAttempt.attempt_id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise NotFoundError(f"Attempt {attempt_id} not found")

    # Only the learner who owns the attempt can cancel it
    if attempt.learner_id != current_learner.learner_id:
        raise ForbiddenError(f"Attempt {attempt_id} does not belong to you")

    # Check if already completed
    if attempt.attempt_status != AttemptStatus.IN_PROGRESS:
        raise BadRequestError(
            f"Cannot cancel attempt that is already {attempt.attempt_status.value.lower()}"
        )

    # Cancel the attempt
    attempt.attempt_status = AttemptStatus.CANCELLED
    return ok(message=f"Attempt {attempt_id} cancelled successfully")
