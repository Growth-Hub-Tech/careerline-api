"""Sample records shared by several sample routes, so ids line up across endpoints.

Skill ids and names match the real question bank (skills 1-3), so the frontend can link a
sample role or test to the real GET /skills and POST /attempts/start.
"""

from datetime import UTC, datetime, timedelta

from app.schemas.common import LevelName, Money
from app.schemas.programmes import Programme, ProgrammeSummary

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


def days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


SKILLS = {
    1: "Frontend Web Development",
    2: "Backend Development",
    3: "Database Management",
    8: "Version Control (Git)",
}

LEVELS = [LevelName.BEGINNER, LevelName.JUNIOR, LevelName.MID, LevelName.ADVANCED]

PROGRAMMES = [
    Programme(
        programme_id=301,
        name="Frontend Engineering Bootcamp",
        provider="Incubate",
        provider_type="incubate",
        mode="hybrid",
        duration_weeks=12,
        price=Money(amount=25_000_000, currency="NGN"),
        summary="HTML, CSS, JavaScript and React from first page to deployed portfolio app.",
        skills=["Frontend Web Development", "Version Control (Git)"],
        role_ids=[101],
        url="https://example.com/programmes/frontend-engineering",
    ),
    Programme(
        programme_id=302,
        name="Backend with Python and FastAPI",
        provider="Incubate",
        provider_type="incubate",
        mode="online",
        duration_weeks=10,
        price=Money(amount=20_000_000, currency="NGN"),
        summary="REST APIs, authentication, databases and testing with Python.",
        skills=["Backend Development", "Database Management"],
        role_ids=[102],
        url="https://example.com/programmes/backend-python",
    ),
    Programme(
        programme_id=303,
        name="SQL for Analysts",
        provider="DataBridge Academy",
        provider_type="partner",
        mode="online",
        duration_weeks=4,
        price=Money(amount=4_500_000, currency="NGN"),
        summary="Queries, joins, indexes and reporting on real business data.",
        skills=["Database Management"],
        role_ids=[102, 103],
        url="https://example.com/programmes/sql-for-analysts",
    ),
]
PROGRAMMES_BY_ID = {programme.programme_id: programme for programme in PROGRAMMES}


def programme_summary(programme_id: int) -> ProgrammeSummary:
    return ProgrammeSummary(**PROGRAMMES_BY_ID[programme_id].model_dump())
