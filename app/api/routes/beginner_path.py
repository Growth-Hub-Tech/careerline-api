from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.beginner_path import BeginnerPath, IntakeQuestionnaire, IntakeSubmission
from app.services.beginner_path import latest_career_paths, load_questionnaire, submit_intake

# The beginner path (Day 13, part 1): intake questionnaire -> ranked career paths
router = APIRouter(prefix="/beginner-path", tags=["Beginner path"], route_class=EnvelopeRoute)


# INTAKE QUESTIONS: personality, goals, time and money (PRD 4.2). Public.
@router.get("/intake", response_model=IntakeQuestionnaire)
async def get_intake_questionnaire():
    return load_questionnaire().public()


# SUBMIT THE INTAKE: answers come back as up to 3 ranked career paths, each with reasons
@router.post(
    "/intake",
    status_code=201,
    response_model=BeginnerPath,
    responses=errors(400, 401),
    description="Every question must be answered once, with option values from GET "
    "/beginner-path/intake (one value for single_choice) and the questionnaire's version. "
    "400: an unknown question or value, a missing answer, or an old version (load the "
    "questionnaire again). programme is null until programmes are real.",
)
async def submit_beginner_intake(
    data: IntakeSubmission,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await submit_intake(db, current_learner.learner_id, data)


# MY CAREER PATHS: the latest intake's paths (none yet: intake_id null, empty list)
@router.get("/recommendations", response_model=BeginnerPath, responses=errors(401))
async def get_my_career_paths(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await latest_career_paths(db, current_learner.learner_id)
