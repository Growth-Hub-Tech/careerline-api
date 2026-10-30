from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    AttemptDifficultyScore,
    AttemptSubskillScore,
    LearnerLevel,
)


# Save difficulty level analytics
async def save_difficulty_stats(db: AsyncSession, attempt_id: int, level_stats: dict):
    # Delete old stats for this attempt first
    existing = await db.execute(
        select(AttemptDifficultyScore).where(AttemptDifficultyScore.attempt_id == attempt_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    # Insert new stats
    for level, data in level_stats.items():
        total = data["total"]
        correct = data["correct"]
        if total == 0:
            continue
        percentage = round((correct / total * 100), 2)
        stat = AttemptDifficultyScore(
            attempt_id=attempt_id,
            difficulty_level=level,
            total_questions=total,
            correct_answers=correct,
            percentage_score=percentage,
        )
        db.add(stat)


# Save subskill analytics
async def save_subskill_stats(db: AsyncSession, attempt_id: int, subskill_stats: dict):
    # Delete old stats for this attempt first
    existing = await db.execute(
        select(AttemptSubskillScore).where(AttemptSubskillScore.attempt_id == attempt_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    # Insert new stats
    for subskill_id, data in subskill_stats.items():
        total = data["total"]
        correct = data["correct"]
        if total == 0:
            continue
        percentage = round((correct / total * 100), 2)
        stat = AttemptSubskillScore(
            attempt_id=attempt_id,
            subskill_id=subskill_id,
            total_questions=total,
            correct_answers=correct,
            percentage_score=percentage,
        )
        db.add(stat)


# Assign proficiency level to learner
async def assign_learner_level(
    db: AsyncSession, learner_id: int, skill_id: int, attempt_id: int, level_id: int
):
    if skill_id is None:
        raise ValueError("skill_id is required to assign a level")
    # Check if learner already has a level for this skill
    # (first() instead of scalar_one_or_none(): old data may hold more than one row)
    existing = await db.execute(
        select(LearnerLevel)
        .where(LearnerLevel.learner_id == learner_id, LearnerLevel.skill_id == skill_id)
        .order_by(LearnerLevel.learner_level_id.desc())
    )
    learner_level = existing.scalars().first()

    if learner_level:
        # Update existing level
        learner_level.level_id = level_id
        learner_level.attempt_id = attempt_id
        learner_level.assigned_at = func.now()  # type: ignore[assignment]  #SQL now() runs in the database, which SQLAlchemy allows
    else:
        # Create new level record
        learner_level = LearnerLevel(
            learner_id=learner_id, skill_id=skill_id, attempt_id=attempt_id, level_id=level_id
        )
        db.add(learner_level)

    return level_id
