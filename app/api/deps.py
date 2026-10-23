from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.models import Learner

__all__ = ["get_db", "get_current_learner", "require_same_learner"]

# OAuth2PasswordBearer tells FastAPI where to look for the token
# tokenUrl is the login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login")


# Dependency that extracts and verifies the current learner from token
async def get_current_learner(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db, scope="function")
) -> Learner:

    # Create a 401 error to raise if anything is wrong
    credentials_error = UnauthorizedError(
        "Invalid or expired token. Please log in again.", headers={"WWW-Authenticate": "Bearer"}
    )

    # Decode the token to get learner_id
    learner_id = decode_access_token(token)
    if learner_id is None:
        raise credentials_error

    # Fetch the learner from database
    result = await db.execute(select(Learner).where(Learner.learner_id == learner_id))
    learner = result.scalar_one_or_none()

    if learner is None:
        raise credentials_error

    return learner


# Stops a logged-in learner from reading or changing another learner's data
def require_same_learner(learner_id: int, current_learner: Learner):
    if learner_id != current_learner.learner_id:
        raise ForbiddenError("You can only access your own data")
