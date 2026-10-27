"""The AI advice for an attempt's weak subskills, as a background job (Day 5).

submit saves plain advice at once and queues "ai_recommendations" for the attempt; this job
asks OpenAI once per weak subskill (in a thread, so it never blocks the event loop) and
replaces the advice. Running it twice only asks the AI again and rewrites the same rows, so a
retry is safe.
"""

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import openai_client
from app.jobs.queue import enqueue
from app.jobs.registry import job
from app.models.models import Subskill, SubskillRecommendation
from app.repositories.recommendation_repo import (
    get_level_name_for_attempt,
    get_skill_name_for_attempt,
)

logger = get_logger(__name__)

JOB_KIND = "ai_recommendations"


def ai_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY)


async def queue_ai_recommendations(db: AsyncSession, attempt_id: int) -> int:
    """Queue the AI job for an attempt (once: the dedupe key is per attempt)."""
    return await enqueue(
        db,
        JOB_KIND,
        {"attempt_id": attempt_id},
        dedupe_key=f"ai-recommendations:attempt:{attempt_id}",
    )


@job(JOB_KIND)
async def add_ai_advice(session: AsyncSession, payload: dict[str, Any]) -> None:
    attempt_id = int(payload["attempt_id"])
    rows = (
        await session.execute(
            select(SubskillRecommendation, Subskill.subskill_name)
            .join(Subskill, SubskillRecommendation.subskill_id == Subskill.subskill_id)
            .where(SubskillRecommendation.attempt_id == attempt_id)
            .order_by(SubskillRecommendation.priority)
        )
    ).all()
    if not rows:
        return
    skill_name = await get_skill_name_for_attempt(session, attempt_id)
    level_name = await get_level_name_for_attempt(session, attempt_id)
    for recommendation, subskill_name in rows:
        score = float(recommendation.percentage_score)
        advice = await asyncio.to_thread(
            openai_client.get_ai_benchmark, skill_name, subskill_name, level_name, score
        )
        recommendation.recommendation_text = advice
    logger.info("ai_recommendations_saved", attempt_id=attempt_id, count=len(rows))
