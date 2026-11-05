"""The organisation and its team roster (Day 21), always the caller's own organisation.

- seats_used is the roster's size; an upload that would take it past seats_total is a 402 and
  saves nothing (updating people already there needs no seat).
- An upload matches people by email (any case): new ones are added, known ones get the name,
  department and role from the upload. One email twice in the same upload is a 400; an unknown
  role is a 404; either way nothing is saved.
- A member's status follows their team invitations (an audit sends them, Day 22), ignoring
  revoked ones: completed when at least one is completed and none is still open, in_progress
  when one is accepted (or some are done and others still open), invited when one is waiting,
  otherwise not_invited. latest_level: the newest result of their team tests in their role's
  main skill (else in any skill).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError, PaymentRequiredError
from app.models.audits import TeamMember
from app.models.history import SkillHistory
from app.models.organisations import Organisation
from app.models.recruiting import Invitation
from app.models.roles import JobRole, JobRoleSkill
from app.schemas.common import LevelName, Page
from app.schemas.organisations import Organisation as OrganisationOut
from app.schemas.organisations import RosterResult, RosterUpload
from app.schemas.organisations import TeamMember as TeamMemberOut
from app.services import subscriptions


def _now() -> datetime:
    return datetime.now(UTC)


def _email(value: str) -> str:
    return value.strip().lower()


async def seats_used(db: AsyncSession, organisation_id: int) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(TeamMember)
        .where(TeamMember.organisation_id == organisation_id)
    )
    return count or 0


async def get_organisation(db: AsyncSession, organisation_id: int) -> OrganisationOut:
    row = await db.get(Organisation, organisation_id)
    if row is None:
        raise NotFoundError(f"Organisation {organisation_id} not found")
    return OrganisationOut(
        organisation_id=row.id,
        name=row.name,
        industry=row.industry,
        size=row.size,
        seats_total=await subscriptions.organisation_seats(db, row.id, row.seats_total),
        seats_used=await seats_used(db, row.id),
        created_at=row.created_at,
    )


def status_from(invitations: list[Invitation]) -> str:
    """not_invited, invited, in_progress or completed (see the module docstring)."""
    now = _now()
    live = [i for i in invitations if i.status != "revoked"]
    waiting = [i for i in live if i.status == "sent" and i.expires_at > now]
    accepted = [i for i in live if i.status == "accepted"]
    done = [i for i in live if i.status == "completed"]
    if done and not waiting and not accepted:
        return "completed"
    if accepted or (done and waiting):
        return "in_progress"
    if waiting:
        return "invited"
    return "not_invited"


async def team_invitations(db: AsyncSession, member_ids: list[int]) -> dict[int, list[Invitation]]:
    out: dict[int, list[Invitation]] = {member_id: [] for member_id in member_ids}
    if not member_ids:
        return out
    rows = await db.scalars(
        select(Invitation)
        .where(Invitation.team_member_id.in_(member_ids))
        .order_by(Invitation.sent_at, Invitation.id)
    )
    for row in rows:
        assert row.team_member_id is not None
        out[row.team_member_id].append(row)
    return out


async def team_results(
    db: AsyncSession, member_ids: list[int]
) -> dict[int, list[tuple[Invitation, SkillHistory]]]:
    """Every finished team test per member, newest first."""
    out: dict[int, list[tuple[Invitation, SkillHistory]]] = {m: [] for m in member_ids}
    if not member_ids:
        return out
    rows = (
        await db.execute(
            select(Invitation, SkillHistory)
            .join(SkillHistory, SkillHistory.attempt_id == Invitation.attempt_id)
            .where(Invitation.team_member_id.in_(member_ids), Invitation.status == "completed")
            .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
        )
    ).all()
    for invitation, history in rows:
        assert invitation.team_member_id is not None
        out[invitation.team_member_id].append((invitation, history))
    return out


async def main_skills(db: AsyncSession, role_ids: set[int]) -> dict[int, int]:
    if not role_ids:
        return {}
    rows = await db.execute(
        select(JobRoleSkill.role_id, JobRoleSkill.skill_id)
        .where(JobRoleSkill.role_id.in_(role_ids))
        .order_by(JobRoleSkill.role_id, JobRoleSkill.position.desc())
    )
    return {role_id: skill_id for role_id, skill_id in rows.all()}  # the lowest position wins


async def role_titles(db: AsyncSession, role_ids: set[int]) -> dict[int, str]:
    if not role_ids:
        return {}
    rows = await db.execute(
        select(JobRole.role_id, JobRole.title).where(JobRole.role_id.in_(role_ids))
    )
    return {role_id: title for role_id, title in rows.all()}


async def members_out(db: AsyncSession, rows: list[TeamMember]) -> list[TeamMemberOut]:
    ids = [r.id for r in rows]
    roles = {r.role_id for r in rows}
    titles = await role_titles(db, roles)
    mains = await main_skills(db, roles)
    invitations = await team_invitations(db, ids)
    results = await team_results(db, ids)
    out = []
    for row in rows:
        mine = results[row.id]
        in_main = [h for i, h in mine if i.skill_id == mains.get(row.role_id)]
        ranked = in_main or [h for _, h in mine]
        newest = ranked[0] if ranked else None
        out.append(
            TeamMemberOut(
                member_id=row.id,
                full_name=row.full_name,
                email=row.email,
                department=row.department,
                role_id=row.role_id,
                role_title=titles.get(row.role_id, ""),
                status=status_from(invitations[row.id]),
                latest_level=LevelName(newest.level.value) if newest is not None else None,
            )
        )
    return out


async def list_members(
    db: AsyncSession, organisation_id: int, department: str | None, limit: int, offset: int
) -> Page[TeamMemberOut]:
    where = [TeamMember.organisation_id == organisation_id]
    if department:
        where.append(func.lower(TeamMember.department) == department.strip().lower())
    total = await db.scalar(select(func.count()).select_from(TeamMember).where(*where))
    rows = list(
        await db.scalars(
            select(TeamMember)
            .where(*where)
            .order_by(TeamMember.full_name, TeamMember.id)
            .limit(limit)
            .offset(offset)
        )
    )
    return Page[TeamMemberOut](
        items=await members_out(db, rows), total=total or 0, limit=limit, offset=offset
    )


async def upload_roster(db: AsyncSession, organisation_id: int, data: RosterUpload) -> RosterResult:
    seen: set[str] = set()
    for item in data.members:
        email = _email(str(item.email))
        if email in seen:
            raise BadRequestError(f"{email} appears more than once in the upload")
        seen.add(email)
    role_ids = {item.role_id for item in data.members}
    known_roles = set(await role_titles(db, role_ids))
    missing = sorted(role_ids - known_roles)
    if missing:
        raise NotFoundError(f"Job role {missing[0]} not found")

    organisation = await db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise NotFoundError(f"Organisation {organisation_id} not found")
    existing = {
        row.email: row
        for row in await db.scalars(
            select(TeamMember).where(
                TeamMember.organisation_id == organisation_id, TeamMember.email.in_(seen)
            )
        )
    }
    new_people = len(seen) - len(existing)
    total = await seats_used(db, organisation_id) + new_people
    seats = await subscriptions.organisation_seats(db, organisation_id, organisation.seats_total)
    if total > seats:
        raise PaymentRequiredError(
            f"The roster would have {total} people and the organisation has "
            f"{seats} seats. Add seats (an organisation plan) or upload fewer."
        )
    now = _now()
    for item in data.members:
        email = _email(str(item.email))
        department = (
            item.department.strip() if item.department and item.department.strip() else None
        )
        row = existing.get(email)
        if row is None:
            db.add(
                TeamMember(
                    organisation_id=organisation_id,
                    full_name=item.full_name.strip(),
                    email=email,
                    department=department,
                    role_id=item.role_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.full_name, row.department, row.role_id = (
                item.full_name.strip(),
                department,
                item.role_id,
            )
            row.updated_at = now
    await db.flush()
    return RosterResult(added=new_people, updated=len(existing), members_total=total)
