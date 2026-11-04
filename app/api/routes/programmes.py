from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.common import Page
from app.schemas.programmes import (
    Programme,
    ProgrammeClick,
    ProgrammeClickRequest,
    ProgrammeSummary,
)
from app.services import programmes as programme_service

# PROGRAMMES (Day 14, real since then): Incubate and partner courses that prepare for a job role
router = APIRouter(prefix="/programmes", tags=["Programmes"], route_class=EnvelopeRoute)


# THE CATALOGUE: Incubate first, then the cheapest. Public.
@router.get("", response_model=Page[ProgrammeSummary], responses=errors(422))
async def list_programmes(
    role_id: int | None = Query(None, description="Only programmes for this job role"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await programme_service.list_programmes(db, role_id, limit, offset)


@router.get("/{programme_id}", response_model=Programme, responses=errors(404))
async def get_programme(programme_id: int, db: AsyncSession = Depends(get_db, scope="function")):
    return await programme_service.get_programme(db, programme_id)


# PROGRAMME CLICK: record the click (for referral reporting), then send the person to redirect_url
@router.post(
    "/{programme_id}/clicks",
    status_code=201,
    response_model=ProgrammeClick,
    responses=errors(401, 404, 422),
    description="Record the click, then send the person to redirect_url (the provider's page "
    "with ref=careerline and the click id). result_id, when given, must be one of your own "
    "results (404 otherwise).",
)
async def record_programme_click(
    programme_id: int,
    data: ProgrammeClickRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await programme_service.record_click(db, programme_id, current_learner.learner_id, data)
