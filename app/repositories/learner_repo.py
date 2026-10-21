from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.models import Learner

logger = get_logger(__name__)


# Fetch a learner by email
async def get_learner_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(Learner).where(Learner.email == email))
    return result.scalar_one_or_none()


# Fetch a learner by ID
async def get_learner_by_id(db: AsyncSession, learner_id: int):
    result = await db.execute(select(Learner).where(Learner.learner_id == learner_id))
    return result.scalar_one_or_none()


# Create a new learner
async def create_learner(db: AsyncSession, full_name: str, email: str, phone: str):
    # Check if learner already exists
    existing = await get_learner_by_email(db, email)
    if existing:
        logger.info("learner_already_exists", learner_id=existing.learner_id)  # never log the email
        return existing.learner_id

    # Create new learner
    new_learner = Learner(full_name=full_name, email=email, phone_number=phone)
    db.add(new_learner)
    await db.flush()  # Flush to get the auto-generated ID without committing

    logger.info("learner_created", learner_id=new_learner.learner_id)
    return new_learner.learner_id
