"""Recruiters (Days 19-20): the organisation's candidates. Access: app/core/permissions.py."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_db
from app.api.routes.organisation_users import acting_member
from app.core.responses import EnvelopeRoute, errors
from app.models.organisations import OrganisationMember
from app.schemas.common import Page
from app.schemas.recruiter import Candidate, CandidateCreate, CandidateReport, CandidateStatus
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


# THE SCORED REPORT (Day 20): once the candidate has finished an invited test (404 before)
@router.get(
    "/candidates/{candidate_id}/report",
    response_model=CandidateReport,
    responses=errors(401, 403, 404),
    description="fit compares the newest result of each invited test with the level the "
    "candidate's role needs (without a role: MID and up strong_fit, JUNIOR possible_fit). "
    "results: every finished invited test, newest first. report_url: the newest result's PDF "
    "(works 15 minutes; null while it is being made: GET again).",
)
async def get_candidate_report(
    candidate_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    def link(token: str) -> str:
        return str(request.url_for("download_result_report", token=token))

    return await recruiting.candidate_report(db, actor, candidate_id, link)
