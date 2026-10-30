"""Job roles, their skills and the job-title ladder (Day 8)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.models import LevelName, Skill
from app.models.roles import JobRole, JobRoleSkill, JobTitle
from app.repositories.question_repo import testable_skill_ids
from app.schemas.common import Page
from app.schemas.roles import JobTitleItem, JobTitleList, Role, RoleSkill, RoleSummary

LEVEL_ORDER = [level.value for level in LevelName]
# A role skill's target level is what the role needs at the mid title
MID_TITLE_LEVEL = "MID"
# Until GET /tests is real, a test is one skill's test: test_id = 200 + skill_id (the sample
# catalogue's numbering)
TEST_ID_OFFSET = 200


def expected_level_for_title(target_at_mid: str, title_level: str) -> str:
    """The level a role needs in one skill at a title: the role skill's target level moved by
    as many steps as the title's expected level is from MID, kept within the 4 levels.

    Example: a main skill at MID needs ADVANCED for a senior; a supporting skill at JUNIOR
    needs BEGINNER for a junior and MID for a senior.
    """
    shift = LEVEL_ORDER.index(title_level) - LEVEL_ORDER.index(MID_TITLE_LEVEL)
    index = LEVEL_ORDER.index(target_at_mid) + shift
    return LEVEL_ORDER[max(0, min(len(LEVEL_ORDER) - 1, index))]


def _summary(role: JobRole) -> RoleSummary:
    return RoleSummary(
        role_id=role.role_id,
        title=role.title,
        slug=role.slug,
        track=role.track,
        summary=role.summary,
    )


async def list_roles(db: AsyncSession, limit: int, offset: int) -> Page[RoleSummary]:
    total = await db.scalar(select(func.count()).select_from(JobRole))
    roles = (
        await db.scalars(select(JobRole).order_by(JobRole.role_id).offset(offset).limit(limit))
    ).all()
    return Page[RoleSummary](
        items=[_summary(r) for r in roles], total=total or 0, limit=limit, offset=offset
    )


async def get_role(db: AsyncSession, role_id: int) -> Role:
    role = await db.get(JobRole, role_id)
    if role is None:
        raise NotFoundError(f"Role {role_id} not found")
    rows = (
        await db.execute(
            select(JobRoleSkill, Skill.skill_name)
            .join(Skill, Skill.skill_id == JobRoleSkill.skill_id)
            .where(JobRoleSkill.role_id == role_id)
            .order_by(JobRoleSkill.position)
        )
    ).all()
    skills = [
        RoleSkill(skill_id=link.skill_id, skill_name=name, target_level=link.target_level)
        for link, name in rows
    ]
    testable = await testable_skill_ids(db, [s.skill_id for s in skills])
    return Role(
        **_summary(role).model_dump(),
        description=role.description,
        skills=skills,
        test_ids=[TEST_ID_OFFSET + s.skill_id for s in skills if s.skill_id in testable],
    )


async def list_job_titles(db: AsyncSession) -> JobTitleList:
    titles = (await db.scalars(select(JobTitle).order_by(JobTitle.rank))).all()
    return JobTitleList(
        items=[
            JobTitleItem(
                title_id=t.title_id,
                slug=t.slug,
                name=t.name,
                rank=t.rank,
                expected_level=t.expected_level,
                description=t.description,
            )
            for t in titles
        ]
    )
