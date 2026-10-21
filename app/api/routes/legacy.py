from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db, require_same_learner
from app.core.exceptions import GoneError, NotFoundError
from app.core.responses import errors
from app.models.models import Learner, TestAttempt
from app.repositories.recommendation_repo import get_learning_pathway
from app.schemas.attempts import AnswerItem
from app.schemas.learners import BehaviouralAnswerItem
from app.services.attempt_service import start_attempt
from app.services.learner_service import get_behavioural_questions, submit_behavioural_answers
from app.services.scoring_service import generate_recommendations, submit_and_score

#LEGACY ROUTES (/api/...): kept only so old clients don't break. Use /api/v1/... instead.
#They are mounted outside the /api/v1 prefix and keep their old success bodies (no envelope);
#errors use the standard error envelope like every other route.
#They need a login token (Authorize in /docs) and the learner always comes from the token.
#learner_id in the body is optional and only checked: a different learner_id gets 403.
router = APIRouter(prefix="/api", tags=["Legacy"], deprecated=True)

#DATA MODELS: This defines what each endpoint expects

#Start Test Attempt. It allows learners to declares their level before taking the test
class LegacyStartAttemptRequest(BaseModel):
    learner_id: int | None = None  #Ignored: the learner comes from the token
    skill_id: int
    declared_level: str  #Learner's self-declared level e.g BEGINNER, JUNIOR, MID, ADVANCED

#Submit Answers Request
class LegacySubmitRequest(BaseModel):
    learner_id: int | None = None  #Ignored: the learner comes from the token
    attempt_id: int
    answers: list[AnswerItem]

#Behavioural Answers Request
class LegacyBehaviouralAnswersRequest(BaseModel):
    learner_id: int | None = None  #Ignored: the learner comes from the token
    attempt_id: int
    answers: list[BehaviouralAnswerItem]


#ENDPOINTS

#Register Learner (retired)
#It created learners with no password, and those learners can never log in,
#so every protected route would reject them. Sign-up is POST /api/v1/auth/register.
@router.post("/register", status_code=410, responses=errors(410))
async def learner_register():
    raise GoneError("This route is retired. Register with POST /api/v1/auth/register (needs a password).")


#Get Behavioural Questions for a specific skill
@router.get("/behavioural-questions/{skill_id}", responses=errors(404, 422))
async def behavioural_questions(skill_id: int, db: AsyncSession = Depends(get_db)):
    #Fetch behavioural questions using the learner service
    questions = await get_behavioural_questions(db=db, skill_id=skill_id)
    if not questions:
        raise NotFoundError(f"Skill {skill_id} not found")
    return {
        "status": "Success",
        "data": questions,
        "message": f"Behavioural questions retrieved for skill_id={skill_id}"
    }


#Submit Behavioural Answers
@router.post("/behavioural-answers", responses=errors(401, 403, 404, 422))
async def behavioural_answers(
    data: LegacyBehaviouralAnswersRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    if data.learner_id is not None:
        require_same_learner(data.learner_id, current_learner)
    learner_id = current_learner.learner_id  #from token
    attempt = await db.get(TestAttempt, data.attempt_id)
    if attempt is None:
        raise NotFoundError(f"Attempt {data.attempt_id} not found")
    require_same_learner(attempt.learner_id, current_learner)

    #Convert list of BehaviouralAnswerItem objects to plain dictionaries
    answers = [
        {
            "question_id": item.question_id,
            "answer_text": item.answer_text
        }
        for item in data.answers
    ]
    #Save answers using the learner service
    result = await submit_behavioural_answers(
        db=db,
        learner_id=learner_id,
        attempt_id=data.attempt_id,
        answers=answers
    )
    return {
        "status": "Success",
        "result": result,
        "message": f"Behavioural answers saved for learner_id={learner_id}"
    }


#Start Test Attempt
@router.post("/attempt/start", responses=errors(400, 401, 403, 422))
async def start_test_attempt(
    data: LegacyStartAttemptRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    if data.learner_id is not None:
        require_same_learner(data.learner_id, current_learner)
    learner_id = current_learner.learner_id  #from token

    #Start attempt using the attempt service
    attempt_data = await start_attempt(
        db=db,
        learner_id=learner_id,
        skill_id=data.skill_id,
        declared_level=data.declared_level
    )
    return {
        "status": "Success",
        "attempt_id": attempt_data["attempt_id"],
        "declared_level": attempt_data["declared_level"],
        "total_questions": attempt_data["total_questions"],
        "questions": attempt_data["questions"],
        "message": f"Test attempt started for learner_id={learner_id} on skill_id={data.skill_id} at {data.declared_level} level"
    }


#Submit Answers and Get Score
@router.post("/attempt/submit", responses=errors(400, 401, 403, 404, 409, 422))
async def submit_answers(
    data: LegacySubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    if data.learner_id is not None:
        require_same_learner(data.learner_id, current_learner)
    learner_id = current_learner.learner_id  #from token

    #Convert list of AnswerItem objects to plain dictionaries
    answers = [
        {
            "question_id": item.question_id,
            "selected_option_id": item.selected_option_id
        }
        for item in data.answers
    ]

    #Score the attempt using the scoring service
    final_result = await submit_and_score(
        db=db,
        attempt_id=data.attempt_id,
        learner_id=learner_id,
        answers=answers
    )

    #Generate recommendations after scoring
    recommendations = await generate_recommendations(
        db=db,
        attempt_id=data.attempt_id,
        learner_id=learner_id
    )

    return {
        "status": "Success",
        "result": final_result,
        "recommendations": recommendations,
        "message": f"Answers submitted and scored for attempt_id={data.attempt_id}"
    }


#Get Learning Pathway
@router.get("/learning-pathway/{learner_id}/{skill_id}", responses=errors(401, 403, 404, 422))
async def learning_pathway(
    learner_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    current_learner: Learner = Depends(get_current_learner)
):
    require_same_learner(learner_id, current_learner)

    #Fetch learning pathway using the recommendation repository
    pathway_rows = await get_learning_pathway(db=db, learner_id=learner_id, skill_id=skill_id)

    if not pathway_rows:
        raise NotFoundError("No learning pathway found for this learner and skill")

    #Format the pathway
    pathway = [
        {
            "priority": row.priority,
            "subskill_name": row.subskill_name,
            "percentage_score": float(row.percentage_score),
            "recommendation": row.recommendation_text
        }
        for row in pathway_rows
    ]

    return {
        "status": "Success",
        "learner_id": learner_id,
        "skill_id": skill_id,
        "learning_pathway": pathway,
        "message": f"Learning pathway retrieved for learner_id={learner_id} and skill_id={skill_id}"
    }
