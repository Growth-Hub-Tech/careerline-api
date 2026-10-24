"""Organisation accounts and their roles (Day 7). Who may call these is decided in
app/core/permissions.py; the rules about owners are here:
- only an owner makes, demotes or removes an owner
- an organisation always keeps at least one owner
- an account belongs to one organisation at most
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Permission, role_can
from app.models.models import Learner
from app.models.organisations import OrganisationMember
from app.schemas.organisation_users import OrganisationUser
from app.services.account_service import find_learner_by_email


def _user(member: OrganisationMember, learner: Learner) -> OrganisationUser:
    return OrganisationUser(
        learner_id=learner.learner_id,
        full_name=learner.full_name,
        email=learner.email,
        role=member.role,
        added_at=member.created_at,
    )


async def list_users(db: AsyncSession, organisation_id: int) -> list[OrganisationUser]:
    rows = (
        await db.execute(
            select(OrganisationMember, Learner)
            .join(Learner, Learner.learner_id == OrganisationMember.learner_id)
            .where(OrganisationMember.organisation_id == organisation_id)
            .order_by(OrganisationMember.created_at, OrganisationMember.id)
        )
    ).all()
    return [_user(member, learner) for member, learner in rows]


def _check_owner_change(actor: OrganisationMember, *roles: str) -> None:
    if "owner" in roles and not role_can(actor.role, Permission.OWNERS_MANAGE):
        raise ForbiddenError("Only an owner can make, change or remove an owner")


async def _owners(db: AsyncSession, organisation_id: int) -> int:
    # Locks the owners\' rows, so two owners leaving at once can\'t leave none
    owners = await db.scalars(
        select(OrganisationMember.id)
        .where(
            OrganisationMember.organisation_id == organisation_id,
            OrganisationMember.role == "owner",
        )
        .with_for_update()
    )
    return len(owners.all())


async def _member(db: AsyncSession, organisation_id: int, learner_id: int):
    row = (
        await db.execute(
            select(OrganisationMember, Learner)
            .join(Learner, Learner.learner_id == OrganisationMember.learner_id)
            .where(
                OrganisationMember.organisation_id == organisation_id,
                OrganisationMember.learner_id == learner_id,
            )
            .with_for_update(of=OrganisationMember)
        )
    ).first()
    if row is None:
        raise NotFoundError("This account is not part of the organisation")
    return row


async def add_user(
    db: AsyncSession, actor: OrganisationMember, email: str, role: str
) -> OrganisationUser:
    _check_owner_change(actor, role)
    learner = await find_learner_by_email(db, email)
    if learner is None:
        raise NotFoundError("No account uses this email. Ask them to sign up first.")
    existing = await db.scalar(
        select(OrganisationMember).where(OrganisationMember.learner_id == learner.learner_id)
    )
    if existing is not None:
        raise ConflictError("This account already belongs to an organisation")
    member = OrganisationMember(
        organisation_id=actor.organisation_id, learner_id=learner.learner_id, role=role
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return _user(member, learner)


async def change_role(
    db: AsyncSession, actor: OrganisationMember, learner_id: int, role: str
) -> OrganisationUser:
    member, learner = await _member(db, actor.organisation_id, learner_id)
    _check_owner_change(actor, member.role, role)
    if (
        member.role == "owner"
        and role != "owner"
        and await _owners(db, member.organisation_id) <= 1
    ):
        raise ConflictError("An organisation needs at least one owner")
    member.role = role
    return _user(member, learner)


async def remove_user(db: AsyncSession, actor: OrganisationMember, learner_id: int) -> None:
    member, _ = await _member(db, actor.organisation_id, learner_id)
    _check_owner_change(actor, member.role)
    if member.role == "owner" and await _owners(db, member.organisation_id) <= 1:
        raise ConflictError("An organisation needs at least one owner")
    await db.delete(member)
