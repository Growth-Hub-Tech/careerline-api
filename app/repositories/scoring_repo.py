from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.models.models import (
    LearnerAnswer, Option, Question, TestAttempt,
    ProficiencyLevel, LevelThreshold, LearnerLevel,
    AttemptDifficultyScore, AttemptSubskillScore, AttemptStatus
)
from app.core.config import settings

#Save a single learner answer
async def save_answer(db: AsyncSession, attempt_id: int, question_id: int, selected_option_id: int):
    #Check if the selected option is correct
    option_result = await db.execute(
        select(Option.is_correct).where(Option.option_id == selected_option_id)
    )
    is_correct = option_result.scalar_one_or_none() or False

    #Save the answer
    answer = LearnerAnswer(
        attempt_id=attempt_id,
        question_id=question_id,
        selected_option_id=selected_option_id,
        is_correct=is_correct
    )
    db.add(answer)
    return is_correct


#Fetch all answers for an attempt
async def get_answers_for_attempt(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(
            LearnerAnswer.is_correct,
            Question.difficulty_level,
            Question.subskill_id
        )
        .join(Option, LearnerAnswer.selected_option_id == Option.option_id)
        .join(Question, LearnerAnswer.question_id == Question.question_id)
        .where(LearnerAnswer.attempt_id == attempt_id)
    )
    return result.all()


#Get proficiency level from score percentage
async def get_level_from_score(db: AsyncSession, percentage: float):
    result = await db.execute(
        select(LevelThreshold).where(
            LevelThreshold.min_score <= percentage,
            LevelThreshold.max_score >= percentage
        )
    )
    threshold = result.scalar_one_or_none()
    return threshold.level_id if threshold else None


#Update test attempt with final score and status
async def update_attempt_score(db: AsyncSession, attempt_id: int, percentage: float, level_id: int, status: AttemptStatus):
    #status must be an AttemptStatus member (PASSED / FAILED), never a raw string
    await db.execute(
        update(TestAttempt)
        .where(TestAttempt.attempt_id == attempt_id)
        .values(
            overall_percentage=percentage,
            assigned_level_id=level_id,
            attempt_status=AttemptStatus(status),
        )
    )


#Save difficulty level analytics
async def save_difficulty_stats(db: AsyncSession, attempt_id: int, level_stats: dict):
    #Delete old stats for this attempt first
    existing = await db.execute(
        select(AttemptDifficultyScore).where(AttemptDifficultyScore.attempt_id == attempt_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    #Insert new stats
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
            percentage_score=percentage
        )
        db.add(stat)


#Save subskill analytics
async def save_subskill_stats(db: AsyncSession, attempt_id: int, subskill_stats: dict):
    #Delete old stats for this attempt first
    existing = await db.execute(
        select(AttemptSubskillScore).where(AttemptSubskillScore.attempt_id == attempt_id)
    )
    for row in existing.scalars().all():
        await db.delete(row)

    #Insert new stats
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
            percentage_score=percentage
        )
        db.add(stat)


#Assign proficiency level to learner
async def assign_learner_level(db: AsyncSession, learner_id: int, skill_id: int, attempt_id: int, level_id: int):
    #Check if learner already has a level for this skill
    existing = await db.execute(
        select(LearnerLevel).where(
            LearnerLevel.learner_id == learner_id,
            LearnerLevel.skill_id == skill_id
        )
    )
    learner_level = existing.scalar_one_or_none()

    if learner_level:
        #Update existing level
        learner_level.level_id = level_id
        learner_level.attempt_id = attempt_id
    else:
        #Create new level record
        learner_level = LearnerLevel(
            learner_id=learner_id,
            skill_id=skill_id,
            attempt_id=attempt_id,
            level_id=level_id
        )
        db.add(learner_level)

    return level_id