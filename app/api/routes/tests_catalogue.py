from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.assessments import AssessmentAccess, AssessmentDetail, AssessmentSummary
from app.schemas.common import Page
from app.services import test_catalogue

# TEST CATALOGUE (Day 17, real since then): every skill that can be tested, with its price in
# credits. Taking a test is /attempts.
router = APIRouter(prefix="/tests", tags=["Tests"], route_class=EnvelopeRoute)


@router.get(
    "",
    response_model=Page[AssessmentSummary],
    responses=errors(422),
    description="Every skill that can be tested now (test_id = 200 + skill_id), by skill id. "
    "price_credits 0 = free.",
)
async def list_tests(
    skill_id: int | None = None,
    role_id: int | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    return await test_catalogue.list_tests(db, skill_id, role_id, limit, offset)


@router.get("/{test_id}", response_model=AssessmentDetail, responses=errors(404))
async def get_test_detail(test_id: int, db: AsyncSession = Depends(get_db, scope="function")):
    return await test_catalogue.get_test(db, test_id)


# CAN I START IT? Free tests always; paid tests need at least their price in credits.
@router.get(
    "/{test_id}/access",
    response_model=AssessmentAccess,
    responses=errors(401, 404),
    description="When can_start is false (reason insufficient_credits), POST /attempts/start "
    "answers 402 payment_required: offer a credit pack (POST /payments/checkout).",
)
async def get_test_access(
    test_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await test_catalogue.get_access(db, test_id, current_learner.learner_id)
