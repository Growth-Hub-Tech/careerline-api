"""Targets and the capability heatmap (Day 23), always the caller's own organisation.

- Targets: the level each role should reach in each skill (optional due date). PUT replaces
  them all (one per role and skill: twice is a 400; an unknown role or skill is a 404; nothing
  changes on an error). Progress: of the roster people in that role, how many have a newest team
  result in that skill at or above the target.
- Heatmap: rows are departments, roles or people; columns are the skills of their roles (roles
  by title, each role's skills in its order). A cell averages the people's newest team result in
  that skill; level is that average's level (the test's score bands); band compares it with the
  target (the highest one among the row's people for that skill, MID when none has one): strong
  meets it, developing is one level short, weak further, not_tested nobody has a result. With
  audit_id: only that audit's people (with the role they had then) and its results.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.audits import AuditMember, OrganisationTarget, TeamMember
from app.models.history import SkillHistory
from app.models.recruiting import Invitation
from app.schemas.common import LevelName
from app.schemas.organisations import (
    Heatmap,
    HeatmapCell,
    HeatmapRow,
    HeatmapSkill,
    Target,
    Targets,
    TargetsUpdate,
)
from app.services import team
from app.services.adaptive_engine import EngineConfig, score_to_level
from app.services.audits import _own_audit, meets, role_skills, skill_names, target_levels
from app.services.recruiting import LEVEL_ORDER

DEFAULT_TARGET = LevelName.MID.value


def _now() -> datetime:
    return datetime.now(UTC)


async def _newest_results(
    db: AsyncSession, member_ids: list[int], audit_id: int | None = None
) -> dict[tuple[int, int], SkillHistory]:
    """(member, skill) -> the member's newest finished team test in that skill."""
    if not member_ids:
        return {}
    query = (
        select(Invitation.team_member_id, Invitation.skill_id, SkillHistory)
        .join(SkillHistory, SkillHistory.attempt_id == Invitation.attempt_id)
        .where(Invitation.team_member_id.in_(member_ids), Invitation.status == "completed")
        .order_by(SkillHistory.recorded_at.desc(), SkillHistory.id.desc())
    )
    if audit_id is not None:
        query = query.where(Invitation.audit_id == audit_id)
    out: dict[tuple[int, int], SkillHistory] = {}
    for member_id, skill_id, history in (await db.execute(query)).all():
        out.setdefault((member_id, skill_id), history)
    return out


# ---------- targets ----------


async def get_targets(db: AsyncSession, organisation_id: int) -> Targets:
    rows = list(
        await db.scalars(
            select(OrganisationTarget).where(OrganisationTarget.organisation_id == organisation_id)
        )
    )
    titles = await team.role_titles(db, {r.role_id for r in rows})
    names = await skill_names(db, {r.skill_id for r in rows})
    people = (
        list(
            await db.scalars(
                select(TeamMember).where(
                    TeamMember.organisation_id == organisation_id,
                    TeamMember.role_id.in_({r.role_id for r in rows}),
                )
            )
        )
        if rows
        else []
    )
    newest = await _newest_results(db, [p.id for p in people])
    items = []
    for row in rows:
        in_role = [p for p in people if p.role_id == row.role_id]
        meeting = sum(
            1
            for p in in_role
            if (p.id, row.skill_id) in newest
            and meets(newest[(p.id, row.skill_id)].level.value, row.target_level.value)
        )
        items.append(
            Target(
                role_id=row.role_id,
                role_title=titles.get(row.role_id, ""),
                skill_id=row.skill_id,
                skill_name=names.get(row.skill_id, ""),
                target_level=LevelName(row.target_level.value),
                due_date=row.due_date,
                members_total=len(in_role),
                members_meeting=meeting,
                progress_percent=round(100 * meeting / len(in_role)) if in_role else 0,
            )
        )
    items.sort(key=lambda t: (t.role_title, t.skill_name, t.role_id, t.skill_id))
    return Targets(organisation_id=organisation_id, items=items)


async def set_targets(db: AsyncSession, organisation_id: int, data: TargetsUpdate) -> Targets:
    seen: set[tuple[int, int]] = set()
    for item in data.items:
        if (item.role_id, item.skill_id) in seen:
            raise BadRequestError(
                f"Role {item.role_id} has two targets for skill {item.skill_id}: send one"
            )
        seen.add((item.role_id, item.skill_id))
    roles = {item.role_id for item in data.items}
    missing_roles = sorted(roles - set(await team.role_titles(db, roles)))
    if missing_roles:
        raise NotFoundError(f"Job role {missing_roles[0]} not found")
    skills = {item.skill_id for item in data.items}
    missing_skills = sorted(skills - set(await skill_names(db, skills)))
    if missing_skills:
        raise NotFoundError(f"Skill {missing_skills[0]} not found")
    await db.execute(
        delete(OrganisationTarget).where(OrganisationTarget.organisation_id == organisation_id)
    )
    now = _now()
    for item in data.items:
        db.add(
            OrganisationTarget(
                organisation_id=organisation_id,
                role_id=item.role_id,
                skill_id=item.skill_id,
                target_level=item.target_level,
                due_date=item.due_date,
                updated_at=now,
            )
        )
    await db.flush()
    return await get_targets(db, organisation_id)


# ---------- the heatmap ----------


def department_key(department: str | None) -> str:
    if not department:
        return "none"
    return re.sub(r"[^a-z0-9]+", "-", department.lower()).strip("-") or "none"


def _band(average: float | None, target: str) -> tuple[LevelName | None, str]:
    if average is None:
        return None, "not_tested"
    level = score_to_level(round(average), EngineConfig())
    gap = LEVEL_ORDER.index(target) - LEVEL_ORDER.index(level)
    return LevelName(level), "strong" if gap <= 0 else "developing" if gap == 1 else "weak"


async def heatmap(
    db: AsyncSession, organisation_id: int, group_by: str, audit_id: int | None
) -> Heatmap:
    # the people in scope, each with their role (then)
    if audit_id is not None:
        audit = await _own_audit(db, organisation_id, audit_id)
        pairs = (
            await db.execute(
                select(TeamMember, AuditMember.role_id)
                .join(AuditMember, AuditMember.team_member_id == TeamMember.id)
                .where(AuditMember.audit_id == audit.id)
            )
        ).all()
        people = [(member, role_id) for member, role_id in pairs]
    else:
        people = [
            (member, member.role_id)
            for member in await db.scalars(
                select(TeamMember).where(TeamMember.organisation_id == organisation_id)
            )
        ]
    role_ids = sorted({role_id for _, role_id in people})
    titles = await team.role_titles(db, set(role_ids))
    by_role = await role_skills(db, role_ids)
    targets = await target_levels(db, organisation_id, role_ids)
    newest = await _newest_results(db, [m.id for m, _ in people], audit_id)

    skill_ids: list[int] = []
    for role_id in sorted(role_ids, key=lambda r: (titles.get(r, ""), r)):
        for skill_id, _ in by_role.get(role_id, []):
            if skill_id not in skill_ids:
                skill_ids.append(skill_id)
    for _, skill_id in sorted(newest):
        if skill_id not in skill_ids:
            skill_ids.append(skill_id)
    names = await skill_names(db, set(skill_ids))

    groups: dict[str, tuple[str, list[tuple[TeamMember, int]]]] = {}
    for member, role_id in people:
        if group_by == "department":
            key, label = department_key(member.department), member.department or "No department"
        elif group_by == "role":
            key, label = str(role_id), titles.get(role_id, "")
        else:
            key, label = str(member.id), member.full_name
        groups.setdefault(key, (label, []))[1].append((member, role_id))

    rows = []
    for key, (label, members) in sorted(groups.items(), key=lambda kv: (kv[1][0], kv[0])):
        cells = []
        for skill_id in skill_ids:
            results = [newest[(m.id, skill_id)] for m, _ in members if (m.id, skill_id) in newest]
            wanted = [targets[(r, skill_id)] for _, r in members if (r, skill_id) in targets]
            target = max(wanted, key=LEVEL_ORDER.index) if wanted else DEFAULT_TARGET
            average = round(sum(h.score for h in results) / len(results), 1) if results else None
            level, band = _band(average, target)
            cells.append(
                HeatmapCell(
                    skill_id=skill_id,
                    average_score=average,
                    level=level,
                    members_tested=len(results),
                    band=band,
                )
            )
        rows.append(HeatmapRow(key=key, label=label, members=len(members), cells=cells))
    return Heatmap(
        organisation_id=organisation_id,
        audit_id=audit_id,
        group_by=group_by,
        skills=[HeatmapSkill(skill_id=s, skill_name=names.get(s, "")) for s in skill_ids],
        rows=rows,
    )
