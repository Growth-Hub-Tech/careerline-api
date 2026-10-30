"""Who is calling: the session from the token, the learner, and their organisation role.

The person always comes from the session, never from the request. Every route also passes
app/core/permissions.authorize (a global dependency) before it runs.
"""

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.models import Learner
from app.models.organisations import OrganisationMember
from app.services.session_service import CurrentSession, find_active_session

__all__ = [
    "get_db",
    "optional_current_session",
    "get_current_session",
    "get_current_learner",
    "current_membership",
    "require_same_learner",
]

# OAuth2PasswordBearer tells FastAPI (and /docs) where to look for the token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login")


def credentials_error() -> UnauthorizedError:
    return UnauthorizedError(
        "Invalid or expired token. Please log in again.", headers={"WWW-Authenticate": "Bearer"}
    )


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = (request.headers.get("Authorization") or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


# The signed-in session, or None (no token, or a token that no longer works). The token must
# name a session that is still open (not signed out, not ended by a password reset, not
# expired) and belongs to the token's learner. Tokens from before Day 6 have no session.
async def optional_current_session(
    request: Request, db: AsyncSession = Depends(get_db, scope="function")
) -> CurrentSession | None:
    token = _bearer_token(request)
    if token is None:
        return None
    decoded = decode_token(token)
    if decoded is None or decoded[1] is None:
        return None
    return await find_active_session(db, decoded[0], decoded[1])


async def get_current_session(
    token: str = Depends(oauth2_scheme),
    current: CurrentSession | None = Depends(optional_current_session),
) -> CurrentSession:
    if current is None:
        raise credentials_error()
    return current


async def get_current_learner(current: CurrentSession = Depends(get_current_session)) -> Learner:
    return current.learner


# The caller's organisation role (None: anonymous, or not part of an organisation)
async def current_membership(
    current: CurrentSession | None = Depends(optional_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> OrganisationMember | None:
    if current is None:
        return None
    return await db.scalar(
        select(OrganisationMember).where(
            OrganisationMember.learner_id == current.learner.learner_id
        )
    )


# Stops a logged-in learner from reading or changing another learner's data
def require_same_learner(learner_id: int, current_learner: Learner):
    if learner_id != current_learner.learner_id:
        raise ForbiddenError("You can only access your own data")
