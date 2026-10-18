from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.api.responses import errors
from app.core.security import hash_password, verify_password, create_access_token
from app.models.models import Learner

#Create router for auth endpoints
router = APIRouter(prefix="/auth", tags=["Authentication"])

#DATA MODELS
class RegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    learner_id: int
    full_name: str


#REGISTER A NEW LEARNER WITH PASSWORD
@router.post("/register", responses=errors(400))
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        #Check if email already exists
        existing = await db.execute(
            select(Learner).where(Learner.email == data.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        #Hash the password before saving
        hashed = hash_password(data.password)

        #Create new learner with hashed password
        new_learner = Learner(
            full_name=data.full_name,
            email=data.email,
            phone_number=data.phone,
            hashed_password=hashed
        )
        db.add(new_learner)
        await db.flush()

        #Create and return token immediately after registration
        token = create_access_token(new_learner.learner_id)

        return {
            "status": "Success",
            "access_token": token,
            "token_type": "bearer",
            "learner_id": new_learner.learner_id,
            "message": f"Learner {data.full_name} registered successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#LOGIN AND GET TOKEN
@router.post("/login", responses=errors(401))
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    try:
        #Find learner by email
        result = await db.execute(
            select(Learner).where(Learner.email == form_data.username)
        )
        learner = result.scalar_one_or_none()

        #Check if learner exists and password is correct
        if not learner or not learner.hashed_password:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not verify_password(form_data.password, learner.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        #Create and return token
        token = create_access_token(learner.learner_id)

        return {
            "access_token": token,
            "token_type": "bearer",
            "learner_id": learner.learner_id,
            "full_name": learner.full_name
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))