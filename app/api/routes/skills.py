from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import NotFoundError
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Skill, Subskill

# Create a router for skill endpoints
router = APIRouter(prefix="/skills", tags=["Skills"], route_class=EnvelopeRoute)


# LIST ALL SKILLS WITH PAGINATION
@router.get("/")
async def list_skills(
    limit: int = 10, offset: int = 0, db: AsyncSession = Depends(get_db, scope="function")
):
    # Fetch skills with pagination
    result = await db.execute(select(Skill).offset(offset).limit(limit))
    skills = result.scalars().all()

    # Count total skills
    count_result = await db.execute(select(Skill))
    total = len(count_result.scalars().all())

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
            }
            for s in skills
        ],
    }


# GET SUBSKILLS FOR A SPECIFIC SKILL
@router.get("/{skill_id}/subskills", responses=errors(404))
async def get_subskills(skill_id: int, db: AsyncSession = Depends(get_db, scope="function")):
    # Check skill exists
    skill_result = await db.execute(select(Skill).where(Skill.skill_id == skill_id))
    skill = skill_result.scalar_one_or_none()
    if not skill:
        raise NotFoundError(f"Skill {skill_id} not found")

    # Fetch subskills
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
