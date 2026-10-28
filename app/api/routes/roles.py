from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.responses import EnvelopeRoute, errors
from app.schemas.common import Page
from app.schemas.roles import JobTitleList, Role, RoleSummary
from app.services import roles_service

# ROLE CATALOGUE (Day 8, real since then): job roles and the skills (with target level) each
# one needs. Public.
router = APIRouter(prefix="/roles", tags=["Skills and roles"], route_class=EnvelopeRoute)
titles_router = APIRouter(
    prefix="/job-titles", tags=["Skills and roles"], route_class=EnvelopeRoute
)


@router.get("", response_model=Page[RoleSummary])
async def list_roles(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await roles_service.list_roles(db, limit, offset)


@router.get("/{role_id}", response_model=Role, responses=errors(404))
async def get_role(role_id: int, db: AsyncSession = Depends(get_db, scope="function")):
    return await roles_service.get_role(db, role_id)


# JOB-TITLE LADDER: intern, junior, mid, senior, lead, and the level expected at each. Public.
@titles_router.get(
    "",
    response_model=JobTitleList,
    description="The job-title ladder, lowest first, with the level expected at each title. "
    "A role skill's target_level is the level at the mid title; for another title it moves by "
    "as many steps as that title's expected_level is from MID (never below BEGINNER or above "
    "ADVANCED).",
)
async def list_job_titles(db: AsyncSession = Depends(get_db, scope="function")):
    return await roles_service.list_job_titles(db)
