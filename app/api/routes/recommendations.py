from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db, require_same_learner
from app.core.exceptions import NotFoundError
from app.core.responses import EnvelopeRoute, errors, ok
from app.models.models import Learner, LearnerLevel, ProficiencyLevel, Skill
from app.repositories.recommendation_repo import get_learning_pathway

# Create a router for recommendation endpoints
router = APIRouter(prefix="/recommendations", tags=["Recommendations"], route_class=EnvelopeRoute)


# GET LEARNING PATHWAY FOR A LEARNER AND SKILL
@router.get("/pathway/{learner_id}/{skill_id}", responses=errors(401, 403, 404))
async def learning_pathway(
    learner_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    require_same_learner(learner_id, current_learner)

    # Fetch learner
    learner_result = await db.execute(select(Learner).where(Learner.learner_id == learner_id))
    learner = learner_result.scalar_one_or_none()
    if not learner:
        raise NotFoundError(f"Learner {learner_id} not found")

    # Fetch skill
    skill_result = await db.execute(select(Skill).where(Skill.skill_id == skill_id))
    skill = skill_result.scalar_one_or_none()
    if not skill:
        raise NotFoundError(f"Skill {skill_id} not found")

    # Fetch learning pathway
    pathway_rows = await get_learning_pathway(db=db, learner_id=learner_id, skill_id=skill_id)
    if not pathway_rows:
        raise NotFoundError("No learning pathway found")

    pathway = [
        {
            "priority": row.priority,
            "subskill_name": row.subskill_name,
            "percentage_score": float(row.percentage_score),
            "recommendation": row.recommendation_text,
        }
        for row in pathway_rows
    ]

    return ok(
        {
            "learner_name": learner.full_name,
            "skill_name": skill.skill_name,
            "learning_pathway": pathway,
        },
        message=f"Learning pathway retrieved for learner_id={learner_id} and skill_id={skill_id}",
    )


# GET CONFIRMED LEVELS FOR A LEARNER ACROSS ALL SKILLS
@router.get("/levels/{learner_id}", responses=errors(401, 403))
async def get_learner_levels(
    learner_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    require_same_learner(learner_id, current_learner)
    result = await db.execute(
        select(LearnerLevel.skill_id, Skill.skill_name, ProficiencyLevel.level_name)
        .join(Skill, LearnerLevel.skill_id == Skill.skill_id)
        .join(ProficiencyLevel, LearnerLevel.level_id == ProficiencyLevel.level_id)
        .where(LearnerLevel.learner_id == learner_id)
    )
    levels = result.all()

    return {
        "learner_id": learner_id,
        "confirmed_levels": [
            {"skill_id": row.skill_id, "skill_name": row.skill_name, "level": row.level_name.value}
            for row in levels
        ],
    }
