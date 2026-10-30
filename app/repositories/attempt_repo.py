import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.models import (
    Option,
    ProficiencyLevel,
    TestAttempt,
)

logger = get_logger(__name__)


# Fetch declared level ID from level name
async def get_level_id_by_name(db: AsyncSession, level_name: str):
    result = await db.execute(
        select(ProficiencyLevel).where(ProficiencyLevel.level_name == level_name)
    )
    level = result.scalar_one_or_none()
    return level.level_id if level else None


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


# Fetch an attempt and lock its row until the transaction ends,
# so two submits of the same attempt can't run at the same time
async def get_attempt_for_update(db: AsyncSession, attempt_id: int):
    result = await db.execute(
        select(TestAttempt).where(TestAttempt.attempt_id == attempt_id).with_for_update()
    )
    return result.scalar_one_or_none()
