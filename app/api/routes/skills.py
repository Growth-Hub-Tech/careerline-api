from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Skill, Subskill
from app.repositories.question_repo import testable_skill_ids

router = APIRouter(prefix="/skills", tags=["Skills"], route_class=EnvelopeRoute)


@router.get("/", responses=errors(422))
async def list_skills(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    result = await db.execute(select(Skill).order_by(Skill.skill_id).offset(offset).limit(limit))
    skills = result.scalars().all()
    testable = await testable_skill_ids(db, [s.skill_id for s in skills])
    total = await db.scalar(select(func.count()).select_from(Skill))

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "skills": [
            {
                "skill_id": s.skill_id,
                "skill_name": s.skill_name,
                "category": s.category,
                "description": s.skill_descr,
                # every level has enough reviewed questions, so a test can start
                "testable": s.skill_id in testable,
            }
            for s in skills
        ],
    }


@router.get("/{skill_id}/subskills", responses=errors(404))
async def get_subskills(skill_id: int, db: AsyncSession = Depends(get_db, scope="function")):
    skill_result = await db.execute(select(Skill).where(Skill.skill_id == skill_id))
    skill = skill_result.scalar_one_or_none()
    if not skill:
        raise NotFoundError(f"Skill {skill_id} not found")

    result = await db.execute(select(Subskill).where(Subskill.skill_id == skill_id))
    subskills = result.scalars().all()

    return {
        "skill_id": skill_id,
        "skill_name": skill.skill_name,
        "total_subskills": len(subskills),
        "subskills": [
            {"subskill_id": s.subskill_id, "subskill_name": s.subskill_name} for s in subskills
        ],
    }
