"""Programmes (Day 14): Incubate and partner courses that prepare for a job role.

- The catalogue comes from seeds/programmes.json (app/db/seed.py). Only active programmes are
  listed or found; a retired one is a 404.
- Lists are in one order: Incubate's own programmes first, then the cheapest, then by id. The
  same order picks THE programme for a career path or a result (best_programmes_for_*).
- A click is recorded before the person leaves for the provider's page; redirect_url carries
  the referral (ref=careerline and the click id) so sign-ups can be traced back.
"""

import secrets
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.exceptions import NotFoundError
from app.models.models import AttemptStatus, Skill, TestAttempt
from app.models.programmes import Programme, ProgrammeClick, ProgrammeRole, ProgrammeSkill
from app.schemas.common import Money, Page
from app.schemas.programmes import Programme as ProgrammeOut
from app.schemas.programmes import ProgrammeClick as ProgrammeClickOut
from app.schemas.programmes import ProgrammeClickRequest, ProgrammeSummary

REFERRAL = "careerline"


def _ordered(query: Select) -> Select:
    # Incubate's own programmes first, then the cheapest, then the lowest id
    return query.order_by(
        (Programme.provider_type != "incubate"), Programme.price_amount, Programme.programme_id
    )


def summary(programme: Programme) -> ProgrammeSummary:
    return ProgrammeSummary(
        programme_id=programme.programme_id,
        name=programme.name,
        provider=programme.provider,
        provider_type=programme.provider_type,
        mode=programme.mode,
        duration_weeks=programme.duration_weeks,
        price=Money(amount=programme.price_amount, currency=programme.currency),
    )


async def list_programmes(
    db: AsyncSession, role_id: int | None, limit: int, offset: int
) -> Page[ProgrammeSummary]:
    query = select(Programme).where(Programme.is_active.is_(True))
    if role_id is not None:
        query = query.where(
            Programme.programme_id.in_(
                select(ProgrammeRole.programme_id).where(ProgrammeRole.role_id == role_id)
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    programmes = (await db.scalars(_ordered(query).limit(limit).offset(offset))).all()
    return Page[ProgrammeSummary](
        items=[summary(p) for p in programmes], total=total, limit=limit, offset=offset
    )


async def _active(db: AsyncSession, programme_id: int) -> Programme:
    programme = await db.get(Programme, programme_id)
    if programme is None or not programme.is_active:
        raise NotFoundError(f"Programme {programme_id} not found")
    return programme


async def get_programme(db: AsyncSession, programme_id: int) -> ProgrammeOut:
    programme = await _active(db, programme_id)
    skills = (
        await db.scalars(
            select(Skill.skill_name)
            .join(ProgrammeSkill, ProgrammeSkill.skill_id == Skill.skill_id)
            .where(ProgrammeSkill.programme_id == programme_id)
            .order_by(ProgrammeSkill.position)
        )
    ).all()
    role_ids = (
        await db.scalars(
            select(ProgrammeRole.role_id)
            .where(ProgrammeRole.programme_id == programme_id)
            .order_by(ProgrammeRole.role_id)
        )
    ).all()
    return ProgrammeOut(
        **summary(programme).model_dump(),
        summary=programme.summary,
        skills=list(skills),
        role_ids=list(role_ids),
        url=programme.url,
    )


def referral_url(url: str, click_id: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("ref", "click")]
    query += [("ref", REFERRAL), ("click", click_id)]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def record_click(
    db: AsyncSession, programme_id: int, learner_id: int, data: ProgrammeClickRequest
) -> ProgrammeClickOut:
    programme = await _active(db, programme_id)
    if data.result_id is not None:
        attempt = await db.get(TestAttempt, data.result_id)
        if (
            attempt is None
            or attempt.learner_id != learner_id
            or attempt.attempt_status != AttemptStatus.COMPLETED
        ):
            raise NotFoundError(f"Result {data.result_id} not found")
    click = ProgrammeClick(
        click_id=f"clk_{secrets.token_hex(8)}",
        programme_id=programme_id,
        learner_id=learner_id,
        source=data.source,
        result_id=data.result_id,
    )
    db.add(click)
    await db.flush()
    await db.refresh(click)
    return ProgrammeClickOut(
        click_id=click.click_id,
        programme_id=programme_id,
        redirect_url=referral_url(programme.url, click.click_id),
        clicked_at=click.clicked_at,
    )


@dataclass(frozen=True)
class PathProgramme:
    programme: ProgrammeSummary | None
    within_budget: bool | None  # None: no programme (or no budget given)


async def best_programmes_for_roles(
    db: AsyncSession, role_ids: list[int], limit: int | None = None
) -> dict[int, PathProgramme]:
    """Each role's programme: the first (in list order) within the price limit (kobo; None = no
    limit), or else the cheapest; PathProgramme(None, None) for a role with none."""
    best: dict[int, PathProgramme] = {r: PathProgramme(None, None) for r in role_ids}
    if not role_ids:
        return best
    rows = (
        await db.execute(
            _ordered(
                select(ProgrammeRole.role_id, Programme)
                .join(Programme, Programme.programme_id == ProgrammeRole.programme_id)
                .where(ProgrammeRole.role_id.in_(role_ids), Programme.is_active.is_(True))
            )
        )
    ).all()
    by_role: dict[int, list[Programme]] = {}
    for role_id, programme in rows:
        by_role.setdefault(role_id, []).append(programme)
    for role_id, programmes in by_role.items():
        within = [p for p in programmes if limit is None or p.price_amount <= limit]
        if within:
            best[role_id] = PathProgramme(summary(within[0]), True)
        else:
            cheapest = min(programmes, key=lambda p: (p.price_amount, p.programme_id))
            best[role_id] = PathProgramme(summary(cheapest), False)
    return best


async def best_programme_for_skill(db: AsyncSession, skill_id: int) -> int | None:
    """The id of the first programme (in list order) that covers this skill."""
    return await db.scalar(
        _ordered(
            select(Programme.programme_id)
            .join(ProgrammeSkill, ProgrammeSkill.programme_id == Programme.programme_id)
            .where(ProgrammeSkill.skill_id == skill_id, Programme.is_active.is_(True))
        ).limit(1)
    )
