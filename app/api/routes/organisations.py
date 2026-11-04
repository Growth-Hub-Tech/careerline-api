"""The organisation audit (Days 21-24): the organisation, its team roster, audits, the capability
heatmap and targets. Always the caller's own organisation (another one's id is a 404).
Access: app/core/permissions.py."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_db
from app.api.routes.organisation_users import acting_member
from app.core.responses import EnvelopeRoute, errors
from app.models.organisations import OrganisationMember
from app.schemas.common import Page
from app.schemas.organisations import Organisation, RosterResult, RosterUpload, TeamMember
from app.services import team

router = APIRouter(
    prefix="/organisations",
    tags=["Organisation audit"],
    route_class=EnvelopeRoute,
    dependencies=[Depends(get_current_session)],
)


# MY ORGANISATION: with its seats (seats_used = people on the roster)
@router.get(
    "/me",
    response_model=Organisation,
    responses=errors(401, 403),
    description="Owners, admins and recruiters. seats_total: how many people the team roster "
    "may hold.",
)
async def get_my_organisation(
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await team.get_organisation(db, actor.organisation_id)


# TEAM ROSTER: everyone the organisation tests, each mapped to a job role (PRD 7.2 step 1)
@router.get(
    "/{organisation_id}/members",
    response_model=Page[TeamMember],
    responses=errors(401, 403, 404, 422),
    description="Owners and admins. By name. department: only that department (any case). "
    "status follows the member's team invitations: not_invited, invited, in_progress, "
    "completed. latest_level: their newest team result in their role's main skill.",
)
async def list_team_members(
    organisation_id: int,
    department: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await team.list_members(db, actor.organisation_id, department, limit, offset)


# UPLOAD THE ROSTER: adds new people and updates existing ones (matched by email)
@router.post(
    "/{organisation_id}/members",
    response_model=RosterResult,
    responses=errors(400, 401, 402, 403, 404, 422),
    description="Owners and admins. Up to 1000 people. People already on the roster (same "
    "email, any case) get the uploaded name, department and role. 402 payment_required: more "
    "people than seats. 404: an unknown role_id. 400: the same email twice. In every error "
    "case nothing is saved.",
)
async def upload_roster(
    organisation_id: int,
    data: RosterUpload,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await team.upload_roster(db, actor.organisation_id, data)
