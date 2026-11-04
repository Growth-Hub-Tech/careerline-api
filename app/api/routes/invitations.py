"""Invitations (Day 19): an organisation invites someone to take one test from the catalogue.
Access: app/core/permissions.py."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.api.routes.organisation_users import acting_member
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.models.organisations import OrganisationMember
from app.schemas.common import Page
from app.schemas.invitations import Invitation, InvitationCreate, InvitationPublic
from app.services import recruiting

router = APIRouter(prefix="/invitations", tags=["Invitations"], route_class=EnvelopeRoute)

FLOW = (
    "sent -> accepted (the invitee opens invite_url, signs in and calls POST "
    "/invitations/token/{token}/accept, which starts the test) -> completed (that test finished; "
    "result_id is set). A sent invitation past expires_at shows as expired."
)


@router.post(
    "",
    status_code=201,
    response_model=Invitation,
    responses=errors(401, 403, 404, 422),
    description="Emails the invitee the link. kind candidate (the default) adds the candidate "
    "by candidate_id or email when needed. 404: unknown test_id, candidate_id or another "
    "organisation_id. " + FLOW,
)
async def send_invitation(
    data: InvitationCreate,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.send_invitation(db, actor, data)


@router.get("", response_model=Page[Invitation], responses=errors(401, 403, 422))
async def list_sent_invitations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.list_invitations(db, actor, limit, offset)


@router.get("/{invitation_id}", response_model=Invitation, responses=errors(401, 403, 404))
async def get_sent_invitation(
    invitation_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.get_invitation(db, actor, invitation_id)


@router.post(
    "/{invitation_id}/revoke",
    response_model=Invitation,
    responses=errors(401, 403, 404, 409),
    description="Revoking twice is fine. 409: the invitation is expired or completed.",
)
async def revoke_invitation(
    invitation_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await recruiting.revoke_invitation(db, actor, invitation_id)


# THE INVITEE: public view of the link, then accept (signed in)
@router.get(
    "/token/{token}",
    response_model=InvitationPublic,
    responses=errors(404, 410),
    description="Public, so the page can show who invited them before they sign in. 410: expired.",
)
async def open_invitation(token: str, db: AsyncSession = Depends(get_db, scope="function")):
    return await recruiting.open_invitation(db, token)


@router.post(
    "/token/{token}/accept",
    response_model=InvitationPublic,
    responses=errors(401, 404, 409, 410),
    description="Starts the invited test (free: the organisation invited them) and returns its "
    "attempt_id; take it with /attempts/{attempt_id}/... Accepting twice is fine; another "
    "account, or a revoked or completed invitation, is a 409; expired is a 410.",
)
async def accept_invitation(
    token: str,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await recruiting.accept_invitation(db, token, current_learner.learner_id)
