"""Audits (Day 22): test an organisation's team for their job roles, then benchmark the results.

- An audit has roles; its members are the roster people in those roles (or the member_ids
  given, which must be on the roster and in those roles) whose role has at least one testable
  skill. Started (now, or later from a draft), it sends each member a team invitation for every
  testable skill of their role: free for them, accepted with any account, valid
  AUDIT_INVITATION_DAYS days.
- Status: draft until started; completed once every member has finished every invitation of
  the audit (revoked ones don't count); otherwise in_progress. Nothing about it is stored but
  started_at: it always follows the invitations.
- Benchmarks, per role and skill with at least one finished test in the audit: the target level
  (the organisation's target, Day 23, else what the role needs, from the job role), the team's average score, how many reached the
  target, and the industry average (everyone's average score in that skill on CareerLine, once
  INDUSTRY_MIN_RESULTS people have one; null before, so nobody's score can be worked out).
"""

import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.email.outbox import send_email
from app.models.audits import Audit, AuditMember, OrganisationTarget, TeamMember
from app.models.history import SkillHistory
from app.models.models import Skill
from app.models.organisations import Organisation, OrganisationMember
from app.models.recruiting import Invitation
from app.models.roles import JobRoleSkill
from app.repositories.question_repo import testable_skill_ids
from app.schemas.common import LevelName, Page
from app.schemas.organisations import Audit as AuditOut
from app.schemas.organisations import (
    AuditCreate,
    AuditDeltas,
    AuditRetest,
    AuditSummary,
    Benchmark,
    MemberDelta,
)
from app.services import team
from app.services.recruiting import LEVEL_ORDER, invite_url

logger = get_logger(__name__)

INDUSTRY_MIN_RESULTS = 5


def _now() -> datetime:
    return datetime.now(UTC)


def meets(level: str, target: str) -> bool:
    return LEVEL_ORDER.index(level) >= LEVEL_ORDER.index(target)


async def role_skills(db: AsyncSession, role_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
    """role -> [(skill_id, target level)] in the role's order."""
    out: dict[int, list[tuple[int, str]]] = {role_id: [] for role_id in role_ids}
    if not role_ids:
        return out
    rows = await db.execute(
        select(JobRoleSkill.role_id, JobRoleSkill.skill_id, JobRoleSkill.target_level)
        .where(JobRoleSkill.role_id.in_(role_ids))
        .order_by(JobRoleSkill.role_id, JobRoleSkill.position)
    )
    for role_id, skill_id, target in rows.all():
        out[role_id].append((skill_id, target.value))
    return out


async def skill_names(db: AsyncSession, skill_ids: set[int]) -> dict[int, str]:
    if not skill_ids:
        return {}
    rows = await db.execute(
        select(Skill.skill_id, Skill.skill_name).where(Skill.skill_id.in_(skill_ids))
    )
    return {skill_id: name for skill_id, name in rows.all()}


async def _own_audit(db: AsyncSession, organisation_id: int, audit_id: int) -> Audit:
    row = await db.get(Audit, audit_id)
    if row is None or row.organisation_id != organisation_id:
        raise NotFoundError(f"Audit {audit_id} not found")
    return row


async def _audit_invitations(db: AsyncSession, audit_ids: list[int]) -> dict[int, list[Invitation]]:
    out: dict[int, list[Invitation]] = {audit_id: [] for audit_id in audit_ids}
    if not audit_ids:
        return out
    for row in await db.scalars(
        select(Invitation).where(Invitation.audit_id.in_(audit_ids)).order_by(Invitation.id)
    ):
        assert row.audit_id is not None
        out[row.audit_id].append(row)
    return out


async def _audit_members(db: AsyncSession, audit_ids: list[int]) -> dict[int, list[AuditMember]]:
    out: dict[int, list[AuditMember]] = {audit_id: [] for audit_id in audit_ids}
    if not audit_ids:
        return out
    for row in await db.scalars(select(AuditMember).where(AuditMember.audit_id.in_(audit_ids))):
        out[row.audit_id].append(row)
    return out


def _progress(
    audit: Audit, members: list[AuditMember], invitations: list[Invitation]
) -> tuple[str, int, datetime | None]:
    """(status, members_completed, completed_at)"""
    by_member: dict[int, list[Invitation]] = defaultdict(list)
    for invitation in invitations:
        if invitation.team_member_id is not None:
            by_member[invitation.team_member_id].append(invitation)
    completed = sum(
        1 for m in members if team.status_from(by_member[m.team_member_id]) == "completed"
    )
    if audit.started_at is None:
        return "draft", completed, None
    if members and completed == len(members):
        done = [i.completed_at for i in invitations if i.completed_at is not None]
        return "completed", completed, max(done) if done else None
    return "in_progress", completed, None


async def _summaries(db: AsyncSession, rows: list[Audit]) -> list[AuditSummary]:
    ids = [r.id for r in rows]
    members = await _audit_members(db, ids)
    invitations = await _audit_invitations(db, ids)
    out = []
    for row in rows:
        status, completed, completed_at = _progress(row, members[row.id], invitations[row.id])
        out.append(
            AuditSummary(
                audit_id=row.id,
                name=row.name,
                status=status,
                role_ids=list(row.role_ids),
                members_total=len(members[row.id]),
                members_completed=completed,
                started_at=row.started_at,
                completed_at=completed_at,
                baseline_audit_id=row.baseline_audit_id,
            )
        )
    return out


async def industry_averages(db: AsyncSession, skill_ids: set[int]) -> dict[int, float]:
    """Everyone's average score per skill, once INDUSTRY_MIN_RESULTS people have a result."""
    if not skill_ids:
        return {}
    newest = (
        select(
            SkillHistory.learner_id,
            SkillHistory.skill_id,
            SkillHistory.score,
            func.row_number()
            .over(
                partition_by=(SkillHistory.learner_id, SkillHistory.skill_id),
                order_by=(SkillHistory.recorded_at.desc(), SkillHistory.id.desc()),
            )
            .label("n"),
        )
        .where(SkillHistory.skill_id.in_(skill_ids))
        .subquery()
    )
    rows = await db.execute(
        select(newest.c.skill_id, func.avg(newest.c.score), func.count())
        .where(newest.c.n == 1)
        .group_by(newest.c.skill_id)
    )
    return {
        skill_id: round(float(average), 1)
        for skill_id, average, people in rows.all()
        if people >= INDUSTRY_MIN_RESULTS
    }


async def target_levels(
    db: AsyncSession, organisation_id: int, role_ids: list[int]
) -> dict[tuple[int, int], str]:
    """(role, skill) -> the organisation's target (Day 23), else the level the role needs."""
    out = {
        (role_id, skill_id): target
        for role_id, skills in (await role_skills(db, role_ids)).items()
        for skill_id, target in skills
    }
    if role_ids:
        for row in await db.scalars(
            select(OrganisationTarget).where(
                OrganisationTarget.organisation_id == organisation_id,
                OrganisationTarget.role_id.in_(role_ids),
            )
        ):
            out[(row.role_id, row.skill_id)] = row.target_level.value
    return out


async def benchmarks(
    db: AsyncSession, audit: Audit, *, with_baseline: bool = True
) -> list[Benchmark]:
    members = (await _audit_members(db, [audit.id]))[audit.id]
    role_of = {m.team_member_id: m.role_id for m in members}
    rows = (
        await db.execute(
            select(Invitation, SkillHistory)
            .join(SkillHistory, SkillHistory.attempt_id == Invitation.attempt_id)
            .where(Invitation.audit_id == audit.id, Invitation.status == "completed")
            .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
        )
    ).all()
    # each member's newest result per skill
    newest: dict[tuple[int, int], SkillHistory] = {}
    for invitation, history in rows:
        if invitation.team_member_id in role_of:
            newest.setdefault((invitation.team_member_id, invitation.skill_id), history)
    by_pair: dict[tuple[int, int], list[SkillHistory]] = defaultdict(list)
    for (member_id, skill_id), history in newest.items():
        by_pair[(role_of[member_id], skill_id)].append(history)
    role_ids = list(audit.role_ids)
    targets = await target_levels(db, audit.organisation_id, role_ids)
    skills = await role_skills(db, role_ids)
    titles = await team.role_titles(db, set(role_ids))
    names = await skill_names(db, {skill_id for _, skill_id in by_pair})
    industry = await industry_averages(db, {skill_id for _, skill_id in by_pair})
    baseline: dict[tuple[int, int], float] = {}
    if with_baseline and audit.baseline_audit_id is not None:
        first = await db.get(Audit, audit.baseline_audit_id)
        if first is not None:
            baseline = {
                (b.role_id, b.skill_id): b.team_average_score
                for b in await benchmarks(db, first, with_baseline=False)
            }
    out = []
    for role_id in role_ids:
        for skill_id, _ in skills.get(role_id, []):
            results = by_pair.get((role_id, skill_id))
            if not results:
                continue
            target = targets.get((role_id, skill_id), LevelName.MID.value)
            out.append(
                Benchmark(
                    role_id=role_id,
                    role_title=titles.get(role_id, ""),
                    skill_id=skill_id,
                    skill_name=names.get(skill_id, ""),
                    target_level=LevelName(target),
                    team_average_score=round(sum(h.score for h in results) / len(results), 1),
                    industry_average_score=industry.get(skill_id),
                    members_at_or_above_target=sum(
                        1 for h in results if meets(h.level.value, target)
                    ),
                    members_tested=len(results),
                )
            )
            before = baseline.get((role_id, skill_id))
            if before is not None:
                out[-1].baseline_average_score = before
                out[-1].score_delta = round(out[-1].team_average_score - before, 1)
    return out


async def _audit_out(db: AsyncSession, row: Audit) -> AuditOut:
    (summary,) = await _summaries(db, [row])
    return AuditOut(**summary.model_dump(), benchmarks=await benchmarks(db, row))


async def list_audits(
    db: AsyncSession, organisation_id: int, limit: int, offset: int
) -> Page[AuditSummary]:
    where = Audit.organisation_id == organisation_id
    total = await db.scalar(select(func.count()).select_from(Audit).where(where))
    rows = list(
        await db.scalars(
            select(Audit)
            .where(where)
            .order_by(Audit.created_at.desc(), Audit.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return Page[AuditSummary](
        items=await _summaries(db, rows), total=total or 0, limit=limit, offset=offset
    )


async def get_audit(db: AsyncSession, organisation_id: int, audit_id: int) -> AuditOut:
    return await _audit_out(db, await _own_audit(db, organisation_id, audit_id))


async def _testable_by_role(db: AsyncSession, role_ids: list[int]) -> dict[int, list[int]]:
    skills = await role_skills(db, role_ids)
    every = {skill_id for pairs in skills.values() for skill_id, _ in pairs}
    testable = await testable_skill_ids(db, list(every)) if every else set()
    return {
        role_id: [skill_id for skill_id, _ in pairs if skill_id in testable]
        for role_id, pairs in skills.items()
    }


async def _pick_members(
    db: AsyncSession, organisation_id: int, data: AuditCreate
) -> list[TeamMember]:
    role_ids = list(dict.fromkeys(data.role_ids))
    missing = sorted(set(role_ids) - set(await team.role_titles(db, set(role_ids))))
    if missing:
        raise NotFoundError(f"Job role {missing[0]} not found")
    if data.member_ids is not None:
        wanted = set(data.member_ids)
        rows = list(
            await db.scalars(
                select(TeamMember).where(
                    TeamMember.organisation_id == organisation_id, TeamMember.id.in_(wanted)
                )
            )
        )
        unknown = sorted(wanted - {r.id for r in rows})
        if unknown:
            raise NotFoundError(f"Team member {unknown[0]} not found")
        for row in rows:
            if row.role_id not in role_ids:
                raise BadRequestError(f"{row.full_name} is not in this audit's roles")
    else:
        rows = list(
            await db.scalars(
                select(TeamMember).where(
                    TeamMember.organisation_id == organisation_id,
                    TeamMember.role_id.in_(role_ids),
                )
            )
        )
    if not rows:
        raise BadRequestError("Nobody on the team roster has these roles")
    testable = await _testable_by_role(db, role_ids)
    chosen = [row for row in rows if testable.get(row.role_id)]
    if not chosen:
        raise BadRequestError("These roles have no test that can be taken yet")
    return sorted(chosen, key=lambda r: (r.full_name, r.id))


async def _send_invitations(db: AsyncSession, actor: OrganisationMember, audit: Audit) -> int:
    members = (await _audit_members(db, [audit.id]))[audit.id]
    testable = await _testable_by_role(db, sorted({m.role_id for m in members}))
    repeat = await _baseline_tests(db, audit)
    people = {
        row.id: row
        for row in await db.scalars(
            select(TeamMember).where(TeamMember.id.in_([m.team_member_id for m in members]))
        )
    }
    names = await skill_names(db, {s for skills in testable.values() for s in skills})
    organisation = await db.scalar(
        select(Organisation.name).where(Organisation.id == audit.organisation_id)
    )
    now = _now()
    sent = 0
    for member in sorted(members, key=lambda m: m.team_member_id):
        person = people[member.team_member_id]
        skills = testable.get(member.role_id, [])
        if repeat is not None:  # a re-test: the tests they had in the baseline audit
            skills = [s for s in skills if s in repeat.get(member.team_member_id, set())]
        for skill_id in skills:
            row = Invitation(
                token=secrets.token_urlsafe(32),
                organisation_id=audit.organisation_id,
                kind="team_member",
                team_member_id=person.id,
                audit_id=audit.id,
                email=person.email,
                full_name=person.full_name,
                skill_id=skill_id,
                message=None,
                status="sent",
                sent_by=actor.learner_id,
                sent_at=now,
                expires_at=now + timedelta(days=settings.AUDIT_INVITATION_DAYS),
            )
            db.add(row)
            await db.flush()
            await send_email(
                db,
                to=person.email,
                template="invitation",
                context={
                    "full_name": person.full_name,
                    "organisation": organisation or "",
                    "test_title": names.get(skill_id, ""),
                    "minutes": settings.ATTEMPT_TIME_LIMIT_MINUTES,
                    "message": f"Part of {audit.name}.",
                    "link": invite_url(row.token),
                    "expires_on": row.expires_at.strftime("%d %b %Y"),
                },
                dedupe_key=f"invitation:{row.id}",
            )
            sent += 1
    audit.started_at = now
    await db.flush()
    logger.info("audit_started", audit_id=audit.id, invitations=sent)
    return sent


async def _baseline_tests(db: AsyncSession, audit: Audit) -> dict[int, set[int]] | None:
    """A re-test's baseline: member -> the skills they were invited to (None: not a re-test)."""
    if audit.baseline_audit_id is None:
        return None
    out: dict[int, set[int]] = defaultdict(set)
    for member_id, skill_id in await db.execute(
        select(Invitation.team_member_id, Invitation.skill_id).where(
            Invitation.audit_id == audit.baseline_audit_id, Invitation.status != "revoked"
        )
    ):
        if member_id is not None:
            out[member_id].add(skill_id)
    return out


async def create_audit(db: AsyncSession, actor: OrganisationMember, data: AuditCreate) -> AuditOut:
    members = await _pick_members(db, actor.organisation_id, data)
    audit = Audit(
        organisation_id=actor.organisation_id,
        name=data.name.strip(),
        role_ids=list(dict.fromkeys(data.role_ids)),
        created_by=actor.learner_id,
        created_at=_now(),
    )
    db.add(audit)
    await db.flush()
    for member in members:
        db.add(AuditMember(audit_id=audit.id, team_member_id=member.id, role_id=member.role_id))
    await db.flush()
    if data.send_invitations:
        await _send_invitations(db, actor, audit)
    return await _audit_out(db, audit)


async def start_audit(db: AsyncSession, actor: OrganisationMember, audit_id: int) -> AuditOut:
    audit = await db.scalar(
        select(Audit)
        .where(Audit.id == audit_id, Audit.organisation_id == actor.organisation_id)
        .with_for_update()
    )
    if audit is None:
        raise NotFoundError(f"Audit {audit_id} not found")
    if audit.started_at is not None:
        raise ConflictError("This audit has already been started")
    await _send_invitations(db, actor, audit)
    return await _audit_out(db, audit)


# ---------- re-tests (Day 24) ----------


async def retest_audit(
    db: AsyncSession, actor: OrganisationMember, audit_id: int, data: AuditRetest
) -> AuditOut:
    """A new audit for the baseline's people (or some of them) and their same tests."""
    first = await _own_audit(db, actor.organisation_id, audit_id)
    if first.started_at is None:
        raise ConflictError("This audit is still a draft: start it before re-testing it")
    members = (await _audit_members(db, [first.id]))[first.id]
    if data.member_ids is not None:
        wanted = set(data.member_ids)
        known = {m.team_member_id for m in members}
        outside = sorted(wanted - known)
        if outside:
            name = await db.scalar(
                select(TeamMember.full_name).where(
                    TeamMember.id == outside[0],
                    TeamMember.organisation_id == actor.organisation_id,
                )
            )
            if name is None:
                raise NotFoundError(f"Team member {outside[0]} not found")
            raise BadRequestError(f"{name} was not in the audit being re-tested")
        members = [m for m in members if m.team_member_id in wanted]
    if not members:
        raise BadRequestError("Nobody to re-test: the audit has no members left")
    audit = Audit(
        organisation_id=actor.organisation_id,
        name=(data.name or f"{first.name} (re-test)").strip()[:120],
        role_ids=list(first.role_ids),
        created_by=actor.learner_id,
        created_at=_now(),
        baseline_audit_id=first.id,
    )
    db.add(audit)
    await db.flush()
    for member in members:
        db.add(
            AuditMember(
                audit_id=audit.id, team_member_id=member.team_member_id, role_id=member.role_id
            )
        )
    await db.flush()
    if data.send_invitations:
        await _send_invitations(db, actor, audit)
    return await _audit_out(db, audit)


async def _newest_in_audit(db: AsyncSession, audit_id: int) -> dict[tuple[int, int], SkillHistory]:
    out: dict[tuple[int, int], SkillHistory] = {}
    rows = await db.execute(
        select(Invitation.team_member_id, Invitation.skill_id, SkillHistory)
        .join(SkillHistory, SkillHistory.attempt_id == Invitation.attempt_id)
        .where(Invitation.audit_id == audit_id, Invitation.status == "completed")
        .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
    )
    for member_id, skill_id, history in rows.all():
        if member_id is not None:
            out.setdefault((member_id, skill_id), history)
    return out


async def audit_deltas(db: AsyncSession, organisation_id: int, audit_id: int) -> AuditDeltas:
    audit = await _own_audit(db, organisation_id, audit_id)
    if audit.baseline_audit_id is None:
        raise BadRequestError("This audit is not a re-test: there is nothing to compare it with")
    members = (await _audit_members(db, [audit.id]))[audit.id]
    people = {
        row.id: row
        for row in await db.scalars(
            select(TeamMember).where(TeamMember.id.in_([m.team_member_id for m in members]))
        )
    }
    pairs = sorted(
        {
            (row.team_member_id, row.skill_id)
            for row in await db.scalars(
                select(Invitation).where(
                    Invitation.audit_id == audit.id, Invitation.status != "revoked"
                )
            )
            if row.team_member_id is not None
        }
    )
    before = await _newest_in_audit(db, audit.baseline_audit_id)
    after = await _newest_in_audit(db, audit.id)
    role_of = {m.team_member_id: m.role_id for m in members}
    names = await skill_names(db, {skill_id for _, skill_id in pairs})
    items = []
    for member_id, skill_id in pairs:
        person = people.get(member_id)
        if person is None:
            continue
        b, a = before.get((member_id, skill_id)), after.get((member_id, skill_id))
        items.append(
            MemberDelta(
                member_id=member_id,
                full_name=person.full_name,
                role_id=role_of.get(member_id, person.role_id),
                skill_id=skill_id,
                skill_name=names.get(skill_id, ""),
                before_score=float(b.score) if b else None,
                before_level=LevelName(b.level.value) if b else None,
                after_score=float(a.score) if a else None,
                after_level=LevelName(a.level.value) if a else None,
                score_delta=float(a.score - b.score) if a and b else None,
            )
        )
    items.sort(key=lambda i: (i.full_name, i.member_id, i.skill_name))
    return AuditDeltas(audit_id=audit.id, baseline_audit_id=audit.baseline_audit_id, items=items)
