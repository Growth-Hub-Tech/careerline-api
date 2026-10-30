"""The organisation's accounts and their roles (Day 7). Access: app/core/permissions.py."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_membership, get_current_session, get_db
from app.core.exceptions import ForbiddenError
from app.core.responses import EnvelopeRoute, errors
from app.models.organisations import OrganisationMember
from app.schemas.common import Acknowledgement
from app.schemas.organisation_users import (
    OrganisationUser,
    OrganisationUserCreate,
    OrganisationUserList,
    OrganisationUserUpdate,
)
from app.services import organisation_service

router = APIRouter(
    prefix="/organisations/{organisation_id}/users",
    tags=["Organisations: accounts and roles"],
    route_class=EnvelopeRoute,
    # Signed in (for /docs' lock icon); the role is checked by app/core/permissions.py
    dependencies=[Depends(get_current_session)],
)


async def acting_member(
    membership: OrganisationMember | None = Depends(current_membership),
) -> OrganisationMember:
    if membership is None:  # authorize has already refused; this is for the type checker
        raise ForbiddenError("This needs an organisation account")
    return membership


@router.get(
    "",
    response_model=OrganisationUserList,
    responses=errors(401, 403),
    description="The organisation's accounts and their roles. Owners and admins.",
)
async def list_organisation_users(
    organisation_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    users = await organisation_service.list_users(db, actor.organisation_id)
    return OrganisationUserList(items=users, total=len(users))


@router.post(
    "",
    status_code=201,
    response_model=OrganisationUser,
    responses=errors(401, 403, 404, 409),
    description="Gives an existing account a role in the organisation (it must have signed up). "
    "Owners and admins; only an owner can add an owner. 409 if the account already belongs to "
    "an organisation.",
)
async def add_organisation_user(
    organisation_id: int,
    data: OrganisationUserCreate,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await organisation_service.add_user(db, actor, str(data.email), data.role)


@router.patch(
    "/{learner_id}",
    response_model=OrganisationUser,
    responses=errors(401, 403, 404, 409),
    description="Changes an account's role. Only an owner changes an owner's role or makes an "
    "owner; the last owner can't be demoted (409).",
)
async def change_organisation_user_role(
    organisation_id: int,
    learner_id: int,
    data: OrganisationUserUpdate,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    return await organisation_service.change_role(db, actor, learner_id, data.role)


@router.delete(
    "/{learner_id}",
    response_model=Acknowledgement,
    responses=errors(401, 403, 404, 409),
    description="Removes an account from the organisation (the account itself stays). Only an "
    "owner removes an owner; the last owner can't leave (409).",
)
async def remove_organisation_user(
    organisation_id: int,
    learner_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    actor: OrganisationMember = Depends(acting_member),
):
    await organisation_service.remove_user(db, actor, learner_id)
    return Acknowledgement()
