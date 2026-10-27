from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.integrations.openai_client import fallback_recommendation
from app.models.models import AttemptStatus
from app.repositories.attempt_repo import get_attempt_for_update, get_attempt_question_ids
from app.repositories.recommendation_repo import (
    get_level_name_for_attempt,
    get_subskill_scores,
    save_recommendations,
)
from app.repositories.scoring_repo import (
    assign_learner_level,
    get_options_by_ids,
    get_pool_question_ids,
    get_question_info,
    save_answer,
    save_difficulty_stats,
    save_subskill_stats,
    update_attempt_score,
)
from app.services.ai_recommendations import ai_enabled, queue_ai_recommendations

logger = get_logger(__name__)

# Suggests a level for the learner if they fail the test.
# For example, if a learner declares themselves as "JUNIOR" but fails, we suggest "BEGINNER".
# If they declare "MID" and fail, we suggest "JUNIOR", and so on.
# If they declare "BEGINNER" and fail, we don't suggest anything since it's the lowest level.
LEVEL_SUGGESTION = {"JUNIOR": "BEGINNER", "MID": "JUNIOR", "ADVANCED": "MID", "BEGINNER": None}


# Errors the global error handler turns into proper HTTP codes instead of a 500
class SubmitError(BadRequestError):
    pass


class AttemptNotFound(NotFoundError):
    pass


class AttemptNotYours(ForbiddenError):
    pass


class AttemptAlreadySubmitted(ConflictError):
    pass


# SUBMIT AND SCORE AN ATTEMPT
async def submit_and_score(db: AsyncSession, attempt_id: int, learner_id: int, answers: list):

    # Load the attempt and lock it (a second submit of the same attempt waits here,
    # then sees it is no longer IN_PROGRESS and gets 409)
    attempt = await get_attempt_for_update(db, attempt_id)
    if attempt is None:
        raise AttemptNotFound(f"Attempt {attempt_id} not found")
    if attempt.learner_id != learner_id:
        raise AttemptNotYours(f"Attempt {attempt_id} does not belong to you")
    if attempt.attempt_status != AttemptStatus.IN_PROGRESS:
        raise AttemptAlreadySubmitted(
            f"Attempt {attempt_id} is already {attempt.attempt_status.value.lower()}; start a new attempt to retake"
        )

    # Which questions were served in this attempt
    served_ids = await get_attempt_question_ids(db, attempt_id)
    if not served_ids:
        # Attempt started before attempt_question existed: allow the attempt's own pool
        served_ids = await get_pool_question_ids(db, attempt.skill_id, attempt.declared_level_id)
        total_questions = min(settings.QUESTIONS_PER_LEVEL, len(served_ids))
    else:
        total_questions = len(served_ids)
    served = set(served_ids)

    # An empty submission would score 0% and use up the attempt
    if not answers:
        raise SubmitError("No answers submitted")

    # Validate: only served questions, one answer per question, option must belong to its question
    seen = set()
    for answer in answers:
        qid = answer["question_id"]
        if qid not in served:
            raise SubmitError(f"Question {qid} is not part of attempt {attempt_id}")
        if qid in seen:
            raise SubmitError(f"Question {qid} was answered more than once")
        seen.add(qid)

    option_ids = [a["selected_option_id"] for a in answers]
    option_map = await get_options_by_ids(db, option_ids)  # option_id -> (question_id, is_correct)
    for answer in answers:
        option = option_map.get(answer["selected_option_id"])
        if option is None or option[0] != answer["question_id"]:
            raise SubmitError(
                f"Option {answer['selected_option_id']} does not belong to question {answer['question_id']}"
            )

    # Save all answers
    for answer in answers:
        await save_answer(db, attempt_id, answer["question_id"], answer["selected_option_id"])
    logger.info("answers_saved", attempt_id=attempt_id, count=len(answers))

    # Score ONLY this submission's answers (never re-read old rows)
    question_info = await get_question_info(
        db, list(seen)
    )  # question_id -> (difficulty, subskill_id)

    correct = 0
    level_stats = {}
    subskill_stats = {}

    for answer in answers:
        level, subskill = question_info[answer["question_id"]]
        is_correct = option_map[answer["selected_option_id"]][1]

        if level not in level_stats:
            level_stats[level] = {"correct": 0, "total": 0}
        if subskill not in subskill_stats:
            subskill_stats[subskill] = {"correct": 0, "total": 0}

        level_stats[level]["total"] += 1
        subskill_stats[subskill]["total"] += 1

        if is_correct:
            correct += 1
            level_stats[level]["correct"] += 1
            subskill_stats[subskill]["correct"] += 1

    # Percentage out of the questions actually served (unanswered = wrong), capped at 100
    percentage = round(min(100.0, (correct / total_questions) * 100), 2) if total_questions else 0.0
    passed = percentage >= settings.PASS_THRESHOLD

    # Get declared level name
    declared_level = await get_level_name_for_attempt(db, attempt_id)

    # Determine pass/fail and level
    # The test was taken AT the declared level, so passing confirms exactly that level.
    # (Before: the level came from the score thresholds, so a JUNIOR test at 100% was saved as ADVANCED.)
    if passed:
        status = AttemptStatus.PASSED
        confirmed_level = declared_level
        level_suggestion = None
        level_id = attempt.declared_level_id
    else:
        status = AttemptStatus.FAILED
        confirmed_level = None
        level_suggestion = LEVEL_SUGGESTION.get(declared_level, None)
        level_id = None

    # Update attempt record
    await update_attempt_score(db, attempt_id, percentage, level_id, status)
    logger.info("attempt_scored", attempt_id=attempt_id, percentage=percentage, status=status.value)

    # Save analytics
    await save_difficulty_stats(db, attempt_id, level_stats)
    await save_subskill_stats(db, attempt_id, subskill_stats)

    # Assign level if passed (skill_id was None before, so levels never showed per skill)
    if passed and level_id:
        await assign_learner_level(db, learner_id, attempt.skill_id, attempt_id, level_id)
        logger.info("level_assigned", attempt_id=attempt_id, level=confirmed_level)

    # Return result
    return {
        "score": correct,
        "total_possible": total_questions,
        "percentage": percentage,
        "declared_level": declared_level,
        "status": status.value.lower(),  # API keeps returning "passed" / "failed"
        "confirmed_level": confirmed_level,
        "level_suggestion": level_suggestion,
        "level_id": level_id,
        "level_breakdown": level_stats,
        "subskill_breakdown": subskill_stats,
    }


# GENERATE RECOMMENDATIONS AFTER SCORING
async def generate_recommendations(db: AsyncSession, attempt_id: int, learner_id: int):

    # Fetch subskill scores
    subskill_scores = await get_subskill_scores(db, attempt_id)
    if not subskill_scores:
        return None

    # Identify weak subskills below threshold
    weak_subskills = [
        s for s in subskill_scores if float(s.percentage_score) < settings.WEAK_THRESHOLD
    ]

    if not weak_subskills:
        logger.info("no_weak_subskills", attempt_id=attempt_id)
        return {"message": "Great job! No weak areas found.", "recommendations": []}

    # Sort by lowest score first. most urgent first
    weak_subskills = sorted(weak_subskills, key=lambda x: float(x.percentage_score))

    # Plain advice now; the AI advice comes from a background job (never inside the request:
    # before Day 5 submit waited for one OpenAI call per weak subskill)
    recommendations = []
    for priority, subskill in enumerate(weak_subskills, start=1):
        score = float(subskill.percentage_score)
        recommendations.append(
            {
                "priority": priority,
                "subskill_id": subskill.subskill_id,
                "subskill_name": subskill.subskill_name,
                "percentage_score": score,
                "recommendation": fallback_recommendation(subskill.subskill_name, score),
            }
        )

    # Save recommendations to database
    await save_recommendations(db, attempt_id, learner_id, recommendations)
    logger.info("recommendations_saved", attempt_id=attempt_id, count=len(recommendations))

    # Queued in this transaction: the job exists only if the submit commits
    ai_advice = "unavailable"
    if ai_enabled():
        await queue_ai_recommendations(db, attempt_id)
        ai_advice = "queued"

    return {
        "total_weak_areas": len(recommendations),
        "ai_advice": ai_advice,
        "recommendations": recommendations,
    }
