from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.responses import EnvelopeRoute, errors, ok
from app.core.security import create_access_token, hash_password, verify_password
from app.models.models import Learner
from app.schemas.auth import RegisterRequest, TokenResponse

# Create router for auth endpoints
router = APIRouter(prefix="/auth", tags=["Authentication"], route_class=EnvelopeRoute)

# Login answers with a standard OAuth2 token body (no envelope), so it has its own router
token_router = APIRouter(prefix="/auth", tags=["Authentication"])


# REGISTER A NEW LEARNER WITH PASSWORD
@router.post("/register", responses=errors(400))
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check if email already exists
    existing = await db.execute(select(Learner).where(Learner.email == data.email))
    if existing.scalar_one_or_none():
        raise BadRequestError("Email already registered")

    # Hash the password before saving
    hashed = hash_password(data.password)

    # Create new learner with hashed password
    new_learner = Learner(
        full_name=data.full_name, email=data.email, phone_number=data.phone, hashed_password=hashed
    )
    db.add(new_learner)
    await db.flush()

    # Create and return token immediately after registration
    token = create_access_token(new_learner.learner_id)

    return ok(
        {
            "access_token": token,
            "token_type": "bearer",
            "learner_id": new_learner.learner_id,
        },
        message=f"Learner {data.full_name} registered successfully",
    )


# LOGIN AND GET TOKEN
@token_router.post("/login", response_model=TokenResponse, responses=errors(401, 422))
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
):
    # Find learner by email
    result = await db.execute(select(Learner).where(Learner.email == form_data.username))
    learner = result.scalar_one_or_none()

    # Check if learner exists and password is correct
    if not learner or not learner.hashed_password:
        raise UnauthorizedError("Invalid email or password")

    if not verify_password(form_data.password, learner.hashed_password):
        raise UnauthorizedError("Invalid email or password")

    # Create and return token
    token = create_access_token(learner.learner_id)

    return {
        "access_token": token,
        "token_type": "bearer",
        "learner_id": learner.learner_id,
        "full_name": learner.full_name,
    }
