"""Recruiters (Days 19-20): the organisation's candidates. Access: app/core/permissions.py."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_db
from app.api.routes.organisation_users import acting_member
from app.core.responses import EnvelopeRoute, errors
from app.models.organisations import OrganisationMember
from app.schemas.common import Page
from app.schemas.recruiter import Candidate, CandidateCreate, CandidateStatus
from app.services import recruiting

router = APIRouter(
    prefix="/recruiter",
    tags=["Recruiter"],
    route_class=EnvelopeRoute,
    dependencies=[Depends(get_current_session)],
)


# MY ORGANISATION'S CANDIDATES: newest first; invite one with POST /invitations
@router.get(
    "/candidates",
    response_model=Page[Candidate],
    responses=errors(401, 403, 422),
    description="Owners, admins and recruiters. status follows the candidate's invitations: "
    "added, invited, in_progress, completed.",
)
async def list_candidates(
    status: CandidateStatus | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.list_candidates(db, actor, status, limit, offset)


@router.post(
    "/candidates",
    status_code=201,
    response_model=Candidate,
    responses=errors(401, 403, 404, 409, 422),
    description="409: that email is already a candidate here. 404: unknown role_id.",
)
async def add_candidate(
    data: CandidateCreate,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.add_candidate(db, actor, data)


@router.get("/candidates/{candidate_id}", response_model=Candidate, responses=errors(401, 403, 404))
async def get_candidate(
    candidate_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.get_candidate(db, actor, candidate_id)
