import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.models import (
    AttemptQuestion,
    Option,
    ProficiencyLevel,
    Question,
    QuestionStatus,
    Subskill,
    TestAttempt,
)
from app.services.question_picking import pick_balanced

logger = get_logger(__name__)


# Create a new test attempt
async def create_attempt(db: AsyncSession, learner_id: int, skill_id: int, declared_level_id: int):
    new_attempt = TestAttempt(
        learner_id=learner_id, skill_id=skill_id, declared_level_id=declared_level_id
    )
    db.add(new_attempt)
    await db.flush()  # Get the auto-generated attempt_id without committing
    logger.info("attempt_created", attempt_id=new_attempt.attempt_id, skill_id=skill_id)
    return new_attempt.attempt_id


# Fetch declared level ID from level name
async def get_level_id_by_name(db: AsyncSession, level_name: str):
    result = await db.execute(
        select(ProficiencyLevel).where(ProficiencyLevel.level_name == level_name)
    )
    level = result.scalar_one_or_none()
    return level.level_id if level else None


# Pick the questions for an attempt: seeded by attempt_id, balanced across subskills,
# and preferring questions this learner has seen least in earlier attempts.
async def get_questions_for_attempt(
    db: AsyncSession,
    skill_id: int,
    difficulty_level: str,
    attempt_id: int,
    learner_id: int,
    count: int,
):
    # Whole pool for this skill and difficulty level: only questions that passed the quality
    # check (Day 8)
    result = await db.execute(
        select(Question)
        .join(Subskill, Question.subskill_id == Subskill.subskill_id)
        .where(
            Subskill.skill_id == skill_id,
            Question.difficulty_level == difficulty_level,
            Question.status == QuestionStatus.ACTIVE,
        )
        .order_by(Question.question_id)
    )
    pool = list(result.scalars().all())
    if not pool:
        return []

    # How often this learner already got each question (earlier attempts on this skill)
    seen_result = await db.execute(
        select(AttemptQuestion.question_id, func.count())
        .join(TestAttempt, TestAttempt.attempt_id == AttemptQuestion.attempt_id)
        .where(
            TestAttempt.learner_id == learner_id,
            TestAttempt.skill_id == skill_id,
            TestAttempt.attempt_id != attempt_id,
        )
        .group_by(AttemptQuestion.question_id)
    )
    seen: dict[int, int] = {row[0]: row[1] for row in seen_result.all()}

    # Same attempt_id -> same selection (reproducible); new attempt -> new selection.
    # Balanced across subskills, least seen first (app/services/question_picking.py)
    return pick_balanced(pool, seen, random.Random(attempt_id), count)


# Fetch options for a question without revealing correct answer
# (order shuffled per attempt, but stable if the same attempt is loaded again)
async def get_options_for_question(
    db: AsyncSession, question_id: int, attempt_id: int | None = None
):
    result = await db.execute(
        select(Option.option_id, Option.option_text)
        .where(Option.question_id == question_id)
        .order_by(Option.option_id)
    )
    options = result.all()
    options_list = [{"option_id": o.option_id, "option_text": o.option_text} for o in options]
    random.Random(f"{attempt_id}-{question_id}").shuffle(options_list)
    return options_list


# Fetch a test attempt by ID
async def get_attempt_by_id(db: AsyncSession, attempt_id: int):
    result = await db.execute(select(TestAttempt).where(TestAttempt.attempt_id == attempt_id))
    return result.scalar_one_or_none()


# Remember exactly which questions were served in this attempt (in order)
async def record_attempt_questions(db: AsyncSession, attempt_id: int, question_ids: list):
    for position, question_id in enumerate(question_ids, start=1):
        db.add(AttemptQuestion(attempt_id=attempt_id, question_id=question_id, position=position))
    await db.flush()


# Question ids served in an attempt (empty for attempts started before this table existed)
async def get_attempt_question_ids(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(AttemptQuestion.question_id)
        .where(AttemptQuestion.attempt_id == attempt_id)
        .order_by(AttemptQuestion.position)
    )
    return list(result.scalars().all())


# Fetch an attempt and lock its row until the transaction ends,
# so two submits of the same attempt can't run at the same time
async def get_attempt_for_update(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id).with_for_update()
    )
    return result.scalar_one_or_none()
