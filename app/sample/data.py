"""Sample records shared by several sample routes, so ids line up across endpoints.

Skill ids and names match the real question bank (skills 1-3), so the frontend can link a
sample role or test to the real GET /skills and POST /attempts/start.
"""

from datetime import UTC, datetime, timedelta

from app.schemas.common import LevelName

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
