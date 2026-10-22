from fastapi import APIRouter, Depends, Request

from app.core.exceptions import ExpiredError
from app.core.responses import ApiResponse
from app.sample import flows
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.schemas.common import Page
from app.schemas.invitations import Invitation, InvitationCreate, InvitationPublic

router = APIRouter(
    prefix="/invitations",
    tags=["Sample: Invitations"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

FLOW_NOTE = (
    "Sample flow: POST /invitations (sent) -> the invitee opens invite_url and calls "
    "POST /invitations/token/{token}/accept (accepted, gets an attempt_id) -> the test is submitted "
    "(completed, gets a result_id; in the sample, POST /api/v1/sample/invitations/{token}/complete)."
)


def _public(invitation: Invitation, message: str | None) -> InvitationPublic:
    return InvitationPublic(
        token=invitation.token,
        status=invitation.status,
        invited_by="Acme Recruiting",
        full_name=invitation.full_name,
        test_id=invitation.test_id,
        test_title=invitation.test_title,
        duration_minutes=30,
        message=message,
        expires_at=invitation.expires_at,
        attempt_id=invitation.attempt_id,
    )


# INVITE SOMEONE TO TAKE A TEST (recruiter: a candidate; organisation: a team member)
@router.post(
    "",
    status_code=201,
    response_model=ApiResponse[Invitation],
    openapi_extra=sample_route(summary_note=FLOW_NOTE),
)
async def send_invitation(
    data: InvitationCreate, request: Request, learner_id: int = Depends(sample_user)
):
    return sample(flows.create_invitation(learner_id, data, str(request.base_url)))


# INVITATIONS I SENT: newest first
@router.get("", response_model=ApiResponse[Page[Invitation]], openapi_extra=sample_route("empty"))
async def list_sent_invitations(
    limit: int = 20,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    invitations = [] if sc.empty else flows.list_invitations(learner_id)
    return sample(
        Page[Invitation](
            items=invitations[offset : offset + limit],
            total=len(invitations),
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/{invitation_id}",
    response_model=ApiResponse[Invitation],
    openapi_extra=sample_route(summary_note=FLOW_NOTE),
)
async def get_sent_invitation(invitation_id: int, learner_id: int = Depends(sample_user)):
    return sample(flows.find_invitation(learner_id, invitation_id))


@router.post(
    "/{invitation_id}/revoke", response_model=ApiResponse[Invitation], openapi_extra=sample_route()
)
async def revoke_invitation(invitation_id: int, learner_id: int = Depends(sample_user)):
    invitation = flows.find_invitation(learner_id, invitation_id)
    return sample(flows.move_invitation(invitation.token, "revoked"))


# THE INVITEE'S VIEW OF THE LINK: public, so the page can show who invited them before login.
# An expired invitation is a 410.
@router.get(
    "/token/{token}",
    response_model=ApiResponse[InvitationPublic],
    openapi_extra=sample_route(summary_note=FLOW_NOTE),
)
async def open_invitation(token: str):
    invitation, message = flows.get_invitation_by_token(token)
    if invitation.status == "expired":
        raise ExpiredError("This invitation has expired. Ask for a new one.")
    return sample(_public(invitation, message))


@router.post(
    "/token/{token}/accept",
    response_model=ApiResponse[InvitationPublic],
    openapi_extra=sample_route(
        summary_note=FLOW_NOTE
        + " Accepting twice is fine; a revoked or completed one is a `conflict` (409)."
    ),
)
async def accept_invitation(token: str, learner_id: int = Depends(sample_user)):
    invitation = flows.move_invitation(token, "accepted")
    _, message = flows.get_invitation_by_token(token)
    return sample(_public(invitation, message))
