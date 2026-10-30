from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.history import SkillHistory
from app.models.models import Learner, Skill, Subskill
from app.schemas.attempts import SubskillRef
from app.schemas.history import SkillHistory as SkillHistoryOut
from app.schemas.history import SkillHistoryEntry
from app.schemas.profile import SkillLevel, SkillProfile

# MY SKILLS (Day 10, real since then): every finished test is saved to the skill history.
# GET /profile and PATCH /profile are still sample routes.
router = APIRouter(prefix="/profile", tags=["Profile"], route_class=EnvelopeRoute)


async def _history(db: AsyncSession, learner_id: int, skill_id: int | None = None):
    query = (
        select(SkillHistory, Skill.skill_name)
        .join(Skill, Skill.skill_id == SkillHistory.skill_id)
        .where(SkillHistory.learner_id == learner_id)
        .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
    )
    if skill_id is not None:
        query = query.where(SkillHistory.skill_id == skill_id)
    return (await db.execute(query)).all()


@router.get(
    "/skills",
    response_model=SkillProfile,
    responses=errors(401),
    description="My level in each skill tested: the latest result per skill, newest first.",
)
async def get_my_skill_profile(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    latest: dict[int, SkillLevel] = {}
    for entry, skill_name in await _history(db, current_learner.learner_id):
        if entry.skill_id not in latest:
            latest[entry.skill_id] = SkillLevel(
                skill_id=entry.skill_id,
                skill_name=skill_name,
                level=entry.level,
                percentage_score=float(entry.score),
                confirmed_at=entry.recorded_at,
            )
    return SkillProfile(learner_id=current_learner.learner_id, skills=list(latest.values()))


@router.get(
    "/skills/history",
    response_model=SkillHistoryOut,
    responses=errors(401),
    description="Every finished test, newest first (optionally for one skill): level, score, "
    "confidence, strengths and weaknesses.",
)
async def get_my_skill_history(
    skill_id: int | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    rows = await _history(db, current_learner.learner_id, skill_id)
    ids = {sid for entry, _ in rows for sid in (*entry.strengths, *entry.weaknesses)}
    names: dict[int, str] = {}
    if ids:
        result = await db.execute(
            select(Subskill.subskill_id, Subskill.subskill_name).where(
                Subskill.subskill_id.in_(ids)
            )
        )
        names = dict(result.tuples().all())

    def refs(subskill_ids: list[int]) -> list[SubskillRef]:
        return [SubskillRef(subskill_id=i, subskill_name=names.get(i, "")) for i in subskill_ids]

    return SkillHistoryOut(
        learner_id=current_learner.learner_id,
        entries=[
            SkillHistoryEntry(
                attempt_id=entry.attempt_id,
                skill_id=entry.skill_id,
                skill_name=skill_name,
                level=entry.level,
                score=entry.score,
                confidence=float(entry.confidence),
                strengths=refs(entry.strengths),
                weaknesses=refs(entry.weaknesses),
                recorded_at=entry.recorded_at,
            )
            for entry, skill_name in rows
        ],
    )
