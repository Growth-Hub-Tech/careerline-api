from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.models import Skill, Subskill

#Create a router for skill endpoints
router = APIRouter(prefix="/skills", tags=["Skills"])


#LIST ALL SKILLS WITH PAGINATION
@router.get("/")
async def list_skills(
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    try:
        #Fetch skills with pagination
        result = await db.execute(
            select(Skill).offset(offset).limit(limit)
        )
        skills = result.scalars().all()

        #Count total skills
        count_result = await db.execute(select(Skill))
        total = len(count_result.scalars().all())

        return {
            "status": "Success",
            "total": total,
            "limit": limit,
            "offset": offset,
            "skills": [
                {
                    "skill_id": s.skill_id,
                    "skill_name": s.skill_name,
                    "category": s.category,
                    "description": s.skill_descr
                }
                for s in skills
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#GET SUBSKILLS FOR A SPECIFIC SKILL
@router.get("/{skill_id}/subskills")
async def get_subskills(skill_id: int, db: AsyncSession = Depends(get_db)):
    try:
        #Check skill exists
        skill_result = await db.execute(
            select(Skill).where(Skill.skill_id == skill_id)
        )
        skill = skill_result.scalar_one_or_none()
        if not skill:
            raise HTTPException(status_code=404, detail=f"Skill {skill_id} not found")

        #Fetch subskills
        result = await db.execute(
            select(Subskill).where(Subskill.skill_id == skill_id)
        )
        subskills = result.scalars().all()

        return {
            "status": "Success",
            "skill_id": skill_id,
            "skill_name": skill.skill_name,
            "total_subskills": len(subskills),
            "subskills": [
                {
                    "subskill_id": s.subskill_id,
                    "subskill_name": s.subskill_name
                }
                for s in subskills
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))