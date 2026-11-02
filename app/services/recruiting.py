"""Recruiting (Days 19-20): candidates and invitations, always within the caller's organisation.

- A candidate is one email per organisation. Their status follows their invitations: completed
  when one is completed, in_progress when one is accepted, invited when one is waiting (sent and
  not expired), otherwise added.
- POST /invitations (kind candidate) finds or adds the candidate by candidate_id or email, then
  emails the invitee the link (FRONTEND_URL/invite/{token}). Revoking a sent or accepted
  invitation is allowed (again: no change); an expired or completed one is a 409.
- Another organisation's candidates and invitations are a 404, never a 403.
- The invitee: GET /invitations/token/{token} is public (who invited them, which test); accepting
  needs a signed-in account (any email: people often use another address), starts the invited
  test free of charge (the organisation invited them) and ties the invitation to that account;
  another account accepting it afterwards is a 409. Expired: 410. Revoked or completed: 409.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, ExpiredError, NotFoundError
from app.core.logging import get_logger
from app.email.outbox import send_email
from app.models.models import Skill
from app.models.organisations import Organisation, OrganisationMember
from app.models.recruiting import Candidate, Invitation
from app.models.roles import JobRole
from app.schemas.common import Page
from app.schemas.invitations import Invitation as InvitationOut
from app.schemas.invitations import InvitationCreate, InvitationPublic
from app.schemas.recruiter import Candidate as CandidateOut
from app.schemas.recruiter import CandidateCreate, CandidateTestResult
from app.services import test_catalogue
from app.services.test_taking_service import start_or_resume

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _email(value: str) -> str:
    return value.strip().lower()


def invite_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/invite/{token}"


def invitation_status(row: Invitation) -> str:
    if row.status == "sent" and row.expires_at <= _now():
        return "expired"
    return row.status


# ---------- candidates ----------


async def _role_titles(db: AsyncSession, role_ids: set[int]) -> dict[int, str]:
    if not role_ids:
        return {}
    rows = await db.execute(
        select(JobRole.role_id, JobRole.title).where(JobRole.role_id.in_(role_ids))
    )
    return {role_id: title for role_id, title in rows.all()}


async def latest_results(
    db: AsyncSession, candidate_ids: list[int]
) -> dict[int, CandidateTestResult]:
    """The newest finished invited test per candidate (Day 20 fills this in)."""
    return {}


def _candidate_status(invitations: list[Invitation]) -> str:
    states = {invitation_status(i) for i in invitations}
    if "completed" in states:
        return "completed"
    if "accepted" in states:
        return "in_progress"
    if "sent" in states:
        return "invited"
    return "added"


async def _candidates_out(db: AsyncSession, rows: list[Candidate]) -> list[CandidateOut]:
    ids = [c.id for c in rows]
    invitations: dict[int, list[Invitation]] = {i: [] for i in ids}
    if ids:
        for inv in await db.scalars(select(Invitation).where(Invitation.candidate_id.in_(ids))):
            invitations[inv.candidate_id].append(inv)  # type: ignore[index]
    titles = await _role_titles(db, {c.role_id for c in rows if c.role_id is not None})
    results = await latest_results(db, ids)
    return [
        CandidateOut(
            candidate_id=c.id,
            full_name=c.full_name,
            email=c.email,
            role_id=c.role_id,
            role_title=titles.get(c.role_id) if c.role_id is not None else None,
            status=_candidate_status(invitations[c.id]),
            added_at=c.created_at,
            latest_result=results.get(c.id),
        )
        for c in rows
    ]


async def own_candidate(db: AsyncSession, organisation_id: int, candidate_id: int) -> Candidate:
    row = await db.get(Candidate, candidate_id)
    if row is None or row.organisation_id != organisation_id:
        raise NotFoundError(f"Candidate {candidate_id} not found")
    return row


async def list_candidates(
    db: AsyncSession, actor: OrganisationMember, status: str | None, limit: int, offset: int
) -> Page[CandidateOut]:
    rows = list(
        await db.scalars(
            select(Candidate)
            .where(Candidate.organisation_id == actor.organisation_id)
            .order_by(Candidate.created_at.desc(), Candidate.id.desc())
        )
    )
    items = await _candidates_out(db, rows)
    if status:
        items = [c for c in items if c.status == status]
    return Page[CandidateOut](
        items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset
    )


async def get_candidate(
    db: AsyncSession, actor: OrganisationMember, candidate_id: int
) -> CandidateOut:
    row = await own_candidate(db, actor.organisation_id, candidate_id)
    (out,) = await _candidates_out(db, [row])
    return out


async def _check_role(db: AsyncSession, role_id: int | None) -> None:
    if role_id is not None and await db.get(JobRole, role_id) is None:
        raise NotFoundError(f"Role {role_id} not found")


async def add_candidate(
    db: AsyncSession, actor: OrganisationMember, data: CandidateCreate
) -> CandidateOut:
    await _check_role(db, data.role_id)
    email = _email(str(data.email))
    exists = await db.scalar(
        select(Candidate.id).where(
            Candidate.organisation_id == actor.organisation_id, Candidate.email == email
        )
    )
    if exists is not None:
        raise ConflictError(f"{email} is already one of your candidates (candidate {exists})")
    row = Candidate(
        organisation_id=actor.organisation_id,
        full_name=data.full_name.strip(),
        email=email,
        role_id=data.role_id,
        added_by=actor.learner_id,
        created_at=_now(),
    )
    db.add(row)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise ConflictError(f"{email} is already one of your candidates") from None
    (out,) = await _candidates_out(db, [row])
    return out


# ---------- invitations ----------


async def _skill_names(db: AsyncSession, skill_ids: set[int]) -> dict[int, str]:
    if not skill_ids:
        return {}
    rows = await db.execute(
        select(Skill.skill_id, Skill.skill_name).where(Skill.skill_id.in_(skill_ids))
    )
    return {skill_id: name for skill_id, name in rows.all()}


def _invitation_out(row: Invitation, skill_name: str) -> InvitationOut:
    status = invitation_status(row)
    return InvitationOut(
        invitation_id=row.id,
        token=row.token,
        kind=row.kind,
        status=status,
        email=row.email,
        full_name=row.full_name,
        test_id=test_catalogue.TEST_ID_OFFSET + row.skill_id,
        test_title=skill_name,
        candidate_id=row.candidate_id,
        organisation_id=row.organisation_id,
        attempt_id=row.attempt_id,
        result_id=row.attempt_id if status == "completed" else None,
        invite_url=invite_url(row.token),
        sent_at=row.sent_at,
        accepted_at=row.accepted_at,
        completed_at=row.completed_at,
        expires_at=row.expires_at,
    )


async def invitations_out(db: AsyncSession, rows: list[Invitation]) -> list[InvitationOut]:
    names = await _skill_names(db, {r.skill_id for r in rows})
    return [_invitation_out(r, names.get(r.skill_id, "")) for r in rows]


async def _candidate_for(
    db: AsyncSession, actor: OrganisationMember, data: InvitationCreate, email: str
) -> Candidate:
    if data.candidate_id is not None:
        return await own_candidate(db, actor.organisation_id, data.candidate_id)
    found = await db.scalar(
        select(Candidate).where(
            Candidate.organisation_id == actor.organisation_id, Candidate.email == email
        )
    )
    if found is not None:
        return found
    row = Candidate(
        organisation_id=actor.organisation_id,
        full_name=data.full_name.strip(),
        email=email,
        added_by=actor.learner_id,
        created_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row


async def send_invitation(
    db: AsyncSession, actor: OrganisationMember, data: InvitationCreate
) -> InvitationOut:
    if data.organisation_id is not None and data.organisation_id != actor.organisation_id:
        raise NotFoundError(f"Organisation {data.organisation_id} not found")
    test = await test_catalogue.get_test(db, data.test_id)  # 404 for a test nobody can take
    email = _email(str(data.email))
    candidate_id = None
    if data.kind == "candidate":
        candidate = await _candidate_for(db, actor, data, email)
        candidate_id = candidate.id
    now = _now()
    row = Invitation(
        token=secrets.token_urlsafe(32),
        organisation_id=actor.organisation_id,
        kind=data.kind,
        candidate_id=candidate_id,
        email=email,
        full_name=data.full_name.strip(),
        skill_id=test.skill_id,
        message=data.message,
        status="sent",
        sent_by=actor.learner_id,
        sent_at=now,
        expires_at=now + timedelta(days=data.expires_in_days),
    )
    db.add(row)
    await db.flush()
    organisation = await db.scalar(
        select(Organisation.name).where(Organisation.id == actor.organisation_id)
    )
    await send_email(
        db,
        to=email,
        template="invitation",
        context={
            "full_name": row.full_name,
            "organisation": organisation or "",
            "test_title": test.title,
            "minutes": test.duration_minutes,
            "message": data.message or "",
            "link": invite_url(row.token),
            "expires_on": row.expires_at.strftime("%d %b %Y"),
        },
        dedupe_key=f"invitation:{row.id}",
    )
    logger.info("invitation_sent", invitation_id=row.id, organisation_id=actor.organisation_id)
    return _invitation_out(row, test.title)


async def _own_invitation(
    db: AsyncSession, actor: OrganisationMember, invitation_id: int
) -> Invitation:
    row = await db.get(Invitation, invitation_id)
    if row is None or row.organisation_id != actor.organisation_id:
        raise NotFoundError(f"Invitation {invitation_id} not found")
    return row


async def list_invitations(
    db: AsyncSession, actor: OrganisationMember, limit: int, offset: int
) -> Page[InvitationOut]:
    where = Invitation.organisation_id == actor.organisation_id
    total = await db.scalar(select(func.count()).select_from(Invitation).where(where))
    rows = list(
        await db.scalars(
            select(Invitation)
            .where(where)
            .order_by(Invitation.sent_at.desc(), Invitation.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return Page[InvitationOut](
        items=await invitations_out(db, rows), total=total or 0, limit=limit, offset=offset
    )


async def get_invitation(
    db: AsyncSession, actor: OrganisationMember, invitation_id: int
) -> InvitationOut:
    (out,) = await invitations_out(db, [await _own_invitation(db, actor, invitation_id)])
    return out


async def revoke_invitation(
    db: AsyncSession, actor: OrganisationMember, invitation_id: int
) -> InvitationOut:
    row = await _own_invitation(db, actor, invitation_id)
    status = invitation_status(row)
    if status in ("expired", "completed"):
        raise ConflictError(f"This invitation is {status}: it cannot be revoked")
    if status != "revoked":
        row.status, row.revoked_at = "revoked", _now()
        await db.flush()
    (out,) = await invitations_out(db, [row])
    return out


# ---------- the invitee ----------


async def _by_token(db: AsyncSession, token: str, *, lock: bool = False) -> Invitation:
    query = select(Invitation).where(Invitation.token == token)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise NotFoundError("This invitation link is not valid")
    if invitation_status(row) == "expired":
        raise ExpiredError("This invitation has expired. Ask for a new one.")
    return row


async def _public(db: AsyncSession, row: Invitation) -> InvitationPublic:
    organisation = await db.scalar(
        select(Organisation.name).where(Organisation.id == row.organisation_id)
    )
    names = await _skill_names(db, {row.skill_id})
    return InvitationPublic(
        token=row.token,
        status=invitation_status(row),
        invited_by=organisation or "",
        full_name=row.full_name,
        test_id=test_catalogue.TEST_ID_OFFSET + row.skill_id,
        test_title=names.get(row.skill_id, ""),
        duration_minutes=settings.ATTEMPT_TIME_LIMIT_MINUTES,
        message=row.message,
        expires_at=row.expires_at,
        attempt_id=row.attempt_id,
    )


async def open_invitation(db: AsyncSession, token: str) -> InvitationPublic:
    return await _public(db, await _by_token(db, token))


async def accept_invitation(db: AsyncSession, token: str, learner_id: int) -> InvitationPublic:
    row = await _by_token(db, token, lock=True)
    if row.status in ("revoked", "completed"):
        raise ConflictError(f"This invitation is {row.status}")
    if row.status == "accepted":
        if row.accepted_by != learner_id:
            raise ConflictError("This invitation was already accepted by another account")
        return await _public(db, row)
    state = await start_or_resume(db, learner_id, row.skill_id, charge=False)
    row.status, row.accepted_at, row.accepted_by = "accepted", _now(), learner_id
    row.attempt_id = state.attempt_id
    await db.flush()
    logger.info("invitation_accepted", invitation_id=row.id, attempt_id=row.attempt_id)
    return await _public(db, row)
