from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    AttemptSubskillScore,
    ProficiencyLevel,
    Skill,
    Subskill,
    SubskillRecommendation,
    TestAttempt,
)


# Fetch subskill performance for an attempt
async def get_subskill_scores(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(
            AttemptSubskillScore.subskill_id,
            AttemptSubskillScore.percentage_score,
            Subskill.subskill_name,
        )
        .join(Subskill, AttemptSubskillScore.subskill_id == Subskill.subskill_id)
        .where(AttemptSubskillScore.attempt_id == attempt_id)
    )
    return result.all()


# Fetch skill name for an attempt
async def get_skill_name_for_attempt(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(Skill.skill_name)
        .join(TestAttempt, TestAttempt.skill_id == Skill.skill_id)
        .where(TestAttempt.attempt_id == attempt_id)
    )
    return result.scalar_one_or_none()


# Fetch learner level name for an attempt
async def get_level_name_for_attempt(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(ProficiencyLevel.level_name)
        .join(TestAttempt, TestAttempt.declared_level_id == ProficiencyLevel.level_id)
        .where(TestAttempt.attempt_id == attempt_id)
    )
    level = result.scalar_one_or_none()
    return str(level.value) if level else "JUNIOR"


# Save recommendations to database
async def save_recommendations(
    db: AsyncSession, attempt_id: int, learner_id: int, recommendations: list
):
    # Delete old recommendations for this attempt first
    existing = await db.execute(
        select(SubskillRecommendation).where(SubskillRecommendation.attempt_id == attempt_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    # Insert new recommendations
    for rec in recommendations:
        recommendation = SubskillRecommendation(
            attempt_id=attempt_id,
            learner_id=learner_id,
            priority=rec["priority"],
            percentage_score=rec["percentage_score"],
            subskill_id=rec["subskill_id"],
            recommendation_text=rec["recommendation"],
        )
        db.add(recommendation)


# Fetch saved recommendations for a learner and skill
async def get_learning_pathway(db: AsyncSession, learner_id: int, skill_id: int):
    # Get latest attempt for this learner and skill
    attempt_result = await db.execute(
        select(TestAttempt.attempt_id)
        .where(TestAttempt.learner_id == learner_id, TestAttempt.skill_id == skill_id)
        .order_by(TestAttempt.start_time.desc())
        .limit(1)
    )
    attempt_id = attempt_result.scalar_one_or_none()
    if not attempt_id:
        return None

    # Fetch recommendations in priority order
    result = await db.execute(
        select(
            SubskillRecommendation.priority,
            SubskillRecommendation.percentage_score,
            SubskillRecommendation.recommendation_text,
            Subskill.subskill_name,
        )
        .join(Subskill, SubskillRecommendation.subskill_id == Subskill.subskill_id)
        .where(SubskillRecommendation.attempt_id == attempt_id)
        .order_by(SubskillRecommendation.priority.asc())
    )
    return result.all()
