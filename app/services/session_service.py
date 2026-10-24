"""Server-side sessions: each sign-in creates one; the token names it; revoking it ends the token.

Sign-out revokes one session, "sign out everywhere" and a password reset revoke all of them, a
password change revokes all the others.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from app.models.accounts import AuthSession
from app.models.models import Learner, LearnerStatus


@dataclass
class CurrentSession:
    session: AuthSession
    learner: Learner


async def start_session(
    db: AsyncSession, learner: Learner, user_agent: str | None = None
) -> tuple[AuthSession, str]:
    """Create a session for the learner; returns it and its access token."""
    session = AuthSession(
        id=uuid.uuid4(),
        learner_id=learner.learner_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    await db.flush()
    return session, create_access_token(learner.learner_id, session_id=str(session.id))


async def find_active_session(
    db: AsyncSession, learner_id: int, session_id: str
) -> CurrentSession | None:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return None
    row = (
        await db.execute(
            select(AuthSession, Learner)
            .join(Learner, Learner.learner_id == AuthSession.learner_id)
            .where(
                AuthSession.id == sid,
                AuthSession.learner_id == learner_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
    ).first()
    if row is None:
        return None
    session, learner = row
    if learner.learner_status == LearnerStatus.INACTIVE:
        return None
    return CurrentSession(session=session, learner=learner)


async def revoke_session(db: AsyncSession, session: AuthSession, reason: str) -> None:
    session.revoked_at = datetime.now(UTC)
    session.revoked_reason = reason


async def revoke_all_sessions(
    db: AsyncSession, learner_id: int, reason: str, *, keep: uuid.UUID | None = None
) -> int:
    query = update(AuthSession).where(
        AuthSession.learner_id == learner_id, AuthSession.revoked_at.is_(None)
    )
    if keep is not None:
        query = query.where(AuthSession.id != keep)
    result = await db.execute(query.values(revoked_at=datetime.now(UTC), revoked_reason=reason))
    return int(result.rowcount)  # type: ignore[attr-defined]
