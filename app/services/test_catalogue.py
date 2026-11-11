"""The test catalogue (Day 17): every skill that can be tested is a test.

- test_id = 200 + skill_id (as in GET /roles); only skills whose every level has enough reviewed
  questions are listed (app/repositories/question_repo.py).
- Every test is the adaptive test of Day 10: all four levels, ADAPTIVE_QUESTION_COUNT
  questions, ATTEMPT_TIME_LIMIT_MINUTES.
- price_credits comes from test_prices (seeds/test_prices.json); a skill not listed is free.
- Access: a free test can always start; a paid one needs at least its price in credits.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.models.models import LevelName, Skill, Subskill
from app.models.payments import TestPrice
from app.models.roles import JobRoleSkill
from app.repositories.question_repo import testable_skill_ids
from app.schemas.assessments import AssessmentAccess, AssessmentDetail, AssessmentSummary
from app.schemas.common import Page
from app.services.payments import credit_balance

# A test is one skill's test: test_id = 200 + skill_id (the numbering every client already uses)
TEST_ID_OFFSET = 200
LEVELS = [LevelName.BEGINNER, LevelName.JUNIOR, LevelName.MID, LevelName.ADVANCED]
WHAT_YOU_GET = [
    "Confirmed level",
    "Score per subskill",
    "Answers explained after the test",
    "PDF report",
    "Learning pathway",
]


async def _summaries(db: AsyncSession, skill_ids: list[int]) -> list[AssessmentSummary]:
    if not skill_ids:
        return []
    skills = (
        await db.scalars(
            select(Skill).where(Skill.skill_id.in_(skill_ids)).order_by(Skill.skill_id)
        )
    ).all()
    prices: dict[int, int] = {
        skill_id: price
        for skill_id, price in (
            await db.execute(
                select(TestPrice.skill_id, TestPrice.price_credits).where(
                    TestPrice.skill_id.in_(skill_ids)
                )
            )
        ).all()
    }
    roles: dict[int, list[int]] = {}
    for skill_id, role_id in (
        await db.execute(
            select(JobRoleSkill.skill_id, JobRoleSkill.role_id)
            .where(JobRoleSkill.skill_id.in_(skill_ids))
            .order_by(JobRoleSkill.role_id)
        )
    ).all():
        roles.setdefault(skill_id, []).append(role_id)
    return [
        AssessmentSummary(
            test_id=TEST_ID_OFFSET + s.skill_id,
            title=s.skill_name,
            skill_id=s.skill_id,
            skill_name=s.skill_name,
            levels=LEVELS,
            format="adaptive",
            question_count=settings.ADAPTIVE_QUESTION_COUNT,
            duration_minutes=settings.ATTEMPT_TIME_LIMIT_MINUTES,
            price_credits=prices.get(s.skill_id, 0),
            role_ids=roles.get(s.skill_id, []),
        )
        for s in skills
    ]


async def list_tests(
    db: AsyncSession, skill_id: int | None, role_id: int | None, limit: int, offset: int
) -> Page[AssessmentSummary]:
    candidates: list[int] | None = None
    if skill_id is not None:
        candidates = [skill_id]
    if role_id is not None:
        in_role = (
            await db.scalars(select(JobRoleSkill.skill_id).where(JobRoleSkill.role_id == role_id))
        ).all()
        candidates = [s for s in (candidates or in_role) if s in set(in_role)]
    testable = sorted(await testable_skill_ids(db, candidates))
    page = testable[offset : offset + limit]
    return Page[AssessmentSummary](
        items=await _summaries(db, page), total=len(testable), limit=limit, offset=offset
    )


async def _testable_skill(db: AsyncSession, test_id: int) -> int:
    skill_id = test_id - TEST_ID_OFFSET
    if skill_id <= 0 or skill_id not in await testable_skill_ids(db, [skill_id]):
        raise NotFoundError(f"Test {test_id} not found")
    return skill_id


async def get_test(db: AsyncSession, test_id: int) -> AssessmentDetail:
    skill_id = await _testable_skill(db, test_id)
    (summary,) = await _summaries(db, [skill_id])
    skill = await db.get(Skill, skill_id)
    subskills = (
        await db.scalars(
            select(Subskill.subskill_name)
            .where(Subskill.skill_id == skill_id)
            .order_by(Subskill.subskill_id)
        )
    ).all()
    return AssessmentDetail(
        **summary.model_dump(),
        description=(skill.skill_descr if skill else None) or "",
        subskills=list(subskills),
        what_you_get=WHAT_YOU_GET,
    )


async def get_access(db: AsyncSession, test_id: int, learner_id: int) -> AssessmentAccess:
    skill_id = await _testable_skill(db, test_id)
    (summary,) = await _summaries(db, [skill_id])
    balance = await credit_balance(db, learner_id)
    price = summary.price_credits
    if price == 0:
        reason, can_start = "free", True
    elif balance >= price:
        reason, can_start = "credits", True
    else:
        reason, can_start = "insufficient_credits", False
    return AssessmentAccess(
        test_id=test_id,
        can_start=can_start,
        reason=reason,
        price_credits=price,
        credits_balance=balance,
    )
