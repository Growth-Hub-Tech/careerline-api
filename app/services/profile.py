"""The person's profile (Day 28): GET /profile and PATCH /profile.

Empty until the person fills it in (the row is made on their first PATCH). PATCH changes only the
fields sent; null clears one. visibility is the share_profile_with_recruiters consent, so the
profile and GET /privacy/consents always agree and every change is kept (consent_events).
completeness: how many of the 9 parts are filled in (the name, which every account has, and the
8 profile fields; goals count once there is one), in percent.
"""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.models import Learner
from app.models.profiles import PersonProfile
from app.schemas.privacy import ConsentChange, ConsentUpdate
from app.schemas.profile import Profile, ProfileUpdate
from app.services import privacy

SHARE_KEY = "share_profile_with_recruiters"
FIELDS = (
    "headline",
    "location",
    "current_role",
    "years_experience",
    "goals",
    "weekly_hours",
    "budget",
    "linkedin_url",
)
LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com", "ng.linkedin.com"}


def _aware(value: Any) -> datetime:
    assert isinstance(value, datetime)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _linkedin(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in LINKEDIN_HOSTS or len(parts.path) < 2:
        raise BadRequestError("linkedin_url must be a LinkedIn link (https://www.linkedin.com/...)")
    return url


def _text(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


async def my_profile(db: AsyncSession, learner: Learner) -> Profile:
    row = await db.get(PersonProfile, learner.learner_id)
    values: dict[str, Any] = {field: getattr(row, field) if row else None for field in FIELDS}
    values["goals"] = list(values["goals"] or [])
    filled = 1 + sum(1 for field in FIELDS if values[field] not in (None, []))
    shared = await privacy.has_consent(db, learner.learner_id, SHARE_KEY)
    return Profile(
        learner_id=learner.learner_id,
        full_name=learner.full_name,
        visibility="recruiters" if shared else "private",
        completeness=round(100 * filled / (len(FIELDS) + 1)),
        updated_at=_aware(row.updated_at if row else learner.created_at),
        **values,
    )


async def update_profile(db: AsyncSession, learner: Learner, data: ProfileUpdate) -> Profile:
    changes = data.model_dump(exclude_unset=True)
    visibility = changes.pop("visibility", None)
    if changes.get("linkedin_url"):
        changes["linkedin_url"] = _linkedin(changes["linkedin_url"])
    if changes:
        row = await db.get(PersonProfile, learner.learner_id, with_for_update=True)
        if row is None:
            row = PersonProfile(learner_id=learner.learner_id, goals=[])
            db.add(row)
        for field, value in changes.items():
            if field == "goals":
                value = list(value or [])
            setattr(row, field, _text(value))
        row.updated_at = datetime.now(UTC)
        await db.flush()
    if visibility is not None:
        shared = visibility == "recruiters"
        change = ConsentChange(key=SHARE_KEY, granted=shared)
        await privacy.update_consents(db, learner, ConsentUpdate(items=[change]))
    return await my_profile(db, learner)
