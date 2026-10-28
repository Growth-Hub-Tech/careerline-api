"""The question bank's stock: how many ACTIVE questions each skill has per level (Day 8)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import Question, QuestionStatus, Subskill
from app.services.question_quality import skill_readiness


async def active_counts(
    db: AsyncSession, skill_ids: list[int] | None = None
) -> dict[int, dict[str, int]]:
    """skill_id -> {level: number of ACTIVE questions} (skills with none are left out)."""
    if skill_ids is not None and not skill_ids:
        return {}
    query = (
        select(Subskill.skill_id, Question.difficulty_level, func.count())
        .join(Subskill, Question.subskill_id == Subskill.subskill_id)
        .where(Question.status == QuestionStatus.ACTIVE)
        .group_by(Subskill.skill_id, Question.difficulty_level)
    )
    if skill_ids is not None:
        query = query.where(Subskill.skill_id.in_(skill_ids))
    counts: dict[int, dict[str, int]] = {}
    for skill_id, level, number in (await db.execute(query)).all():
        counts.setdefault(skill_id, {})[level.value] = number
    return counts


async def testable_skill_ids(db: AsyncSession, skill_ids: list[int] | None = None) -> set[int]:
    """The skills whose every level has at least MIN_ACTIVE_QUESTIONS_PER_LEVEL active questions."""
    minimum = settings.MIN_ACTIVE_QUESTIONS_PER_LEVEL
    return {
        skill_id
        for skill_id, by_level in (await active_counts(db, skill_ids)).items()
        if skill_readiness(by_level, minimum)[0]
    }


async def readiness(db: AsyncSession, skill_id: int) -> tuple[bool, dict[str, int]]:
    """(can this skill be tested?, how many active questions each short level still needs)"""
    counts = (await active_counts(db, [skill_id])).get(skill_id, {})
    return skill_readiness(counts, settings.MIN_ACTIVE_QUESTIONS_PER_LEVEL)
