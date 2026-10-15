from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.models import TestAttempt, ProficiencyLevel, Question, Option, Subskill, AttemptQuestion
import random

#Create a new test attempt
async def create_attempt(db: AsyncSession, learner_id: int, skill_id: int, declared_level_id: int):
    new_attempt = TestAttempt(
        learner_id=learner_id,
        skill_id=skill_id,
        declared_level_id=declared_level_id
    )
    db.add(new_attempt)
    await db.flush() #Get the auto-generated attempt_id without committing
    print(f"New attempt created with ID: {new_attempt.attempt_id}")
    return new_attempt.attempt_id

#Fetch declared level ID from level name
async def get_level_id_by_name(db: AsyncSession, level_name: str):
    result = await db.execute(
        select(ProficiencyLevel).where(ProficiencyLevel.level_name == level_name)
    )
    level = result.scalar_one_or_none()
    return level.level_id if level else None

#Fetch 25 random questions for a skill and difficulty level
async def get_questions_for_attempt(db: AsyncSession, skill_id: int, difficulty_level: str):
    #Fetch all questions for this skill and difficulty level
    result = await db.execute(
        select(Question)
        .join(Subskill, Question.subskill_id == Subskill.subskill_id)
        .where(
            Subskill.skill_id == skill_id,
            Question.difficulty_level == difficulty_level
        )
    )
    all_questions = result.scalars().all()

    #Randomly sample 25 questions — replaces ORDER BY RAND()
    sample_size = min(25, len(all_questions))
    selected = random.sample(list(all_questions), sample_size)

    return selected

#Fetch options for a question without revealing correct answer
async def get_options_for_question(db: AsyncSession, question_id: int):
    result = await db.execute(
        select(Option.option_id, Option.option_text)
        .where(Option.question_id == question_id)
    )
    options = result.all()
    #Shuffle options randomly so correct answer is not always in same position
    options_list = [{"option_id": o.option_id, "option_text": o.option_text} for o in options]
    random.shuffle(options_list)
    return options_list

#Fetch a test attempt by ID
async def get_attempt_by_id(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id)
    )
    return result.scalar_one_or_none()


#Remember exactly which questions were served in this attempt (in order)
async def record_attempt_questions(db: AsyncSession, attempt_id: int, question_ids: list):
    for position, question_id in enumerate(question_ids, start=1):
        db.add(AttemptQuestion(attempt_id=attempt_id, question_id=question_id, position=position))
    await db.flush()


#Question ids served in an attempt (empty for attempts started before this table existed)
async def get_attempt_question_ids(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(AttemptQuestion.question_id)
        .where(AttemptQuestion.attempt_id == attempt_id)
        .order_by(AttemptQuestion.position)
    )
    return list(result.scalars().all())


#Fetch an attempt and lock its row until the transaction ends,
#so two submits of the same attempt can't run at the same time
async def get_attempt_for_update(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(TestAttempt)
        .where(TestAttempt.attempt_id == attempt_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()
