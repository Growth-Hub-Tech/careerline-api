"""Demo accounts and a demo company, for the test server only: `python -m app.db.demo`.

scripts/start.sh runs it on every start when DEMO_DATA_ON_START=true. It refuses to run in
production. Safe to run again: it creates what is missing and puts the demo accounts back to
the documented password and roles (someone may have changed them while testing).

The accounts and the password are documented in docs/api.md ("Demo accounts"). They are fake
and public on purpose: never use them anywhere real.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import AsyncSessionLocal
from app.models.models import Learner, LearnerStatus
from app.models.organisations import Organisation, OrganisationMember

REPO_ROOT = Path(__file__).resolve().parents[2]

# The demo company has the sample organisation's id (app/sample/routes/organisations.py), so
# the organisation routes that still give sample answers answer for it.
DEMO_ORGANISATION_ID = 41
DEMO_COMPANY = "Demo Company Ltd"
# Public and fake on purpose (test server only)
DEMO_PASSWORD = "demo-password-not-secret"


@dataclass(frozen=True)
class DemoAccount:
    email: str
    full_name: str
    role: str | None  # role in the demo company; None = a learner


DEMO_ACCOUNTS = (
    DemoAccount("demo.learner@example.com", "Demo Learner", None),
    DemoAccount("demo.learner2@example.com", "Demo Learner Two", None),
    DemoAccount("demo.owner@example.com", "Demo Owner", "owner"),
    DemoAccount("demo.admin@example.com", "Demo Admin", "admin"),
    DemoAccount("demo.recruiter@example.com", "Demo Recruiter", "recruiter"),
)


class DemoDataRefused(Exception):
    pass


async def _account(db: AsyncSession, demo: DemoAccount) -> tuple[Learner, bool]:
    learner = await db.scalar(select(Learner).where(Learner.email == demo.email))
    if learner is None:
        learner = Learner(
            full_name=demo.full_name,
            email=demo.email,
            phone_number="+2348000000000",
            hashed_password=await asyncio.to_thread(hash_password, DEMO_PASSWORD),
            learner_status=LearnerStatus.ACTIVE,
            email_verified_at=datetime.now(UTC),
        )
        db.add(learner)
        await db.flush()
        return learner, True
    if not await asyncio.to_thread(verify_password, DEMO_PASSWORD, learner.hashed_password):
        learner.hashed_password = await asyncio.to_thread(hash_password, DEMO_PASSWORD)
    learner.learner_status = LearnerStatus.ACTIVE
    if learner.email_verified_at is None:
        learner.email_verified_at = datetime.now(UTC)
    return learner, False


async def load_into(db: AsyncSession) -> dict[str, Any]:
    if settings.is_production:
        raise DemoDataRefused("demo data is never loaded in production")
    created = 0
    company = await db.get(Organisation, DEMO_ORGANISATION_ID)
    if company is None:
        company = Organisation(
            id=DEMO_ORGANISATION_ID, name=DEMO_COMPANY, industry="Technology", size="11-50"
        )
        db.add(company)
        await db.flush()
        # The id was set by hand: move the counter past it so new organisations don't collide
        await db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('organisations', 'id'),"
                " (SELECT max(id) FROM organisations))"
            )
        )
    for demo in DEMO_ACCOUNTS:
        learner, new = await _account(db, demo)
        created += int(new)
        member = await db.scalar(
            select(OrganisationMember).where(OrganisationMember.learner_id == learner.learner_id)
        )
        if demo.role is None:
            if member is not None:
                await db.delete(member)
        elif member is None:
            db.add(
                OrganisationMember(
                    organisation_id=DEMO_ORGANISATION_ID,
                    learner_id=learner.learner_id,
                    role=demo.role,
                )
            )
        else:
            member.organisation_id = DEMO_ORGANISATION_ID
            member.role = demo.role
    return {"accounts_created": created, "accounts": len(DEMO_ACCOUNTS), "company": company.name}


async def load() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        result = await load_into(db)
        await db.commit()
    return result


def main() -> None:
    from app.db.session import engine

    async def _run() -> dict[str, Any]:
        try:
            return await load()
        finally:
            await engine.dispose()

    result = asyncio.run(_run())
    print(
        f"Demo data: {result['accounts']} accounts ({result['accounts_created']} new), "
        f"company {result['company']!r} (id {DEMO_ORGANISATION_ID})"
    )


if __name__ == "__main__":
    main()
