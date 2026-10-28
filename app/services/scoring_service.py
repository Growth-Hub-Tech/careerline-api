"""Recommendations after a test. (The fixed pass/fail scoring that lived here was retired on
Day 10: app/services/test_taking_service.py scores the adaptive test.)"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.openai_client import fallback_recommendation
from app.repositories.recommendation_repo import get_subskill_scores, save_recommendations
from app.services.ai_recommendations import ai_enabled, queue_ai_recommendations

logger = get_logger(__name__)


# GENERATE RECOMMENDATIONS AFTER SCORING
async def generate_recommendations(
    db: AsyncSession, attempt_id: int, learner_id: int, weak_subskill_ids: list[int] | None = None
):
    """Advice for the weak subskills of a finished test. weak_subskill_ids: the adaptive
    engine's weaknesses (Day 10); without it, every subskill under WEAK_THRESHOLD percent."""

    # Fetch subskill scores
    subskill_scores = await get_subskill_scores(db, attempt_id)
    if not subskill_scores:
        return None

    # Identify weak subskills
    if weak_subskill_ids is not None:
        weak_subskills = [s for s in subskill_scores if s.subskill_id in set(weak_subskill_ids)]
    else:
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
