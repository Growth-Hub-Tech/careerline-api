from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.models import Learner
from app.services.session_service import CurrentSession, find_active_session

__all__ = ["get_db", "get_current_session", "get_current_learner", "require_same_learner"]

# OAuth2PasswordBearer tells FastAPI where to look for the token
# tokenUrl is the login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login")


def _credentials_error() -> UnauthorizedError:
    return UnauthorizedError(
        "Invalid or expired token. Please log in again.", headers={"WWW-Authenticate": "Bearer"}
    )


# The signed-in session from the token. The token must name a session that is still open
# (not signed out, not ended by a password reset, not expired) and belongs to its learner.
async def get_current_session(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db, scope="function")
) -> CurrentSession:
    decoded = decode_token(token)
    if decoded is None:
        raise _credentials_error()
    learner_id, session_id = decoded
    if session_id is None:
        raise _credentials_error()  # tokens from before Day 6 have no session: log in again
    current = await find_active_session(db, learner_id, session_id)
    if current is None:
        raise _credentials_error()
    return current


# Dependency that gives the current learner from the session
async def get_current_learner(current: CurrentSession = Depends(get_current_session)) -> Learner:
    return current.learner


# Stops a logged-in learner from reading or changing another learner's data
def require_same_learner(learner_id: int, current_learner: Learner):
    if learner_id != current_learner.learner_id:
        raise ForbiddenError("You can only access your own data")
