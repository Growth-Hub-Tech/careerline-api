from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from app.models.models import (
    LearnerAnswer, Option, Question, TestAttempt,
    ProficiencyLevel, LevelThreshold, LearnerLevel,
    AttemptDifficultyScore, AttemptSubskillScore, AttemptStatus, Subskill
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


#option_id -> (question_id, is_correct) for the given options
async def get_options_by_ids(db: AsyncSession, option_ids: list):
    if not option_ids:
        return {}
    result = await db.execute(
        select(Option.option_id, Option.question_id, Option.is_correct)
        .where(Option.option_id.in_(set(option_ids)))
    )
    return {row.option_id: (row.question_id, bool(row.is_correct)) for row in result.all()}


#question_id -> (difficulty level name, subskill_id)
async def get_question_info(db: AsyncSession, question_ids: list):
    if not question_ids:
        return {}
    result = await db.execute(
        select(Question.question_id, Question.difficulty_level, Question.subskill_id)
        .where(Question.question_id.in_(question_ids))
    )
    return {row.question_id: (row.difficulty_level.value, row.subskill_id) for row in result.all()}


#All question ids an attempt could have been served (its skill at its declared level).
#Only used for attempts started before attempt_question existed.
async def get_pool_question_ids(db: AsyncSession, skill_id: int, declared_level_id: int):
    level = await db.execute(
        select(ProficiencyLevel.level_name).where(ProficiencyLevel.level_id == declared_level_id)
    )
    level_name = level.scalar_one_or_none()
    if level_name is None:
        return []
    result = await db.execute(
        select(Question.question_id)
        .join(Subskill, Question.subskill_id == Subskill.subskill_id)
        .where(Subskill.skill_id == skill_id, Question.difficulty_level == level_name)
    )
    return list(result.scalars().all())


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
            end_time=func.now(),
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
    if skill_id is None:
        raise ValueError("skill_id is required to assign a level")
    #Check if learner already has a level for this skill
    #(first() instead of scalar_one_or_none(): old data may hold more than one row)
    existing = await db.execute(
        select(LearnerLevel)
        .where(
            LearnerLevel.learner_id == learner_id,
            LearnerLevel.skill_id == skill_id
        )
        .order_by(LearnerLevel.learner_level_id.desc())
    )
    learner_level = existing.scalars().first()

    if learner_level:
        #Update existing level
        learner_level.level_id = level_id
        learner_level.attempt_id = attempt_id
        learner_level.assigned_at = func.now()  #when this level was (re)confirmed
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