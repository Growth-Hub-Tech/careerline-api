from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.models import Learner

#OAuth2PasswordBearer tells FastAPI where to look for the token
#tokenUrl is the login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


#Dependency that extracts and verifies the current learner from token
async def get_current_learner(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> Learner:

    #Create a 401 exception to raise if anything is wrong
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"}
    )

    #Decode the token to get learner_id
    learner_id = decode_access_token(token)
    if learner_id is None:
        raise credentials_exception

    #Fetch the learner from database
    result = await db.execute(
        select(Learner).where(Learner.learner_id == learner_id)
    )
    learner = result.scalar_one_or_none()

    if learner is None:
        raise credentials_exception

    return learner