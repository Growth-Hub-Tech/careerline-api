from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import LEVELS
from app.schemas.assessments import AssessmentAccess, AssessmentDetail, AssessmentSummary
from app.schemas.common import Page

router = APIRouter(
    prefix="/tests",
    tags=["Sample: Tests"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

TESTS = [
    AssessmentDetail(
        test_id=201,
        title="Frontend Web Development",
        skill_id=1,
        skill_name="Frontend Web Development",
        levels=LEVELS,
        format="adaptive",
        question_count=25,
        duration_minutes=30,
        price_credits=0,
        role_ids=[101],
        description="HTML, CSS, JavaScript and React. Questions get harder or easier as you answer.",
        subskills=["HTML semantics", "CSS layout", "JavaScript fundamentals", "React"],
        what_you_get=["Confirmed level", "Score per subskill", "PDF report", "Learning pathway"],
    ),
    AssessmentDetail(
        test_id=202,
        title="Backend Development",
        skill_id=2,
        skill_name="Backend Development",
        levels=LEVELS,
        format="adaptive",
        question_count=25,
        duration_minutes=30,
        price_credits=2,
        role_ids=[102],
        description="REST APIs, authentication and server logic.",
        subskills=["REST APIs", "Authentication", "Server logic", "Error handling"],
        what_you_get=["Confirmed level", "Score per subskill", "PDF report", "Learning pathway"],
    ),
    AssessmentDetail(
        test_id=203,
        title="Database Management",
        skill_id=3,
        skill_name="Database Management",
        levels=LEVELS,
        format="adaptive",
        question_count=25,
        duration_minutes=30,
        price_credits=2,
        role_ids=[102, 103],
        description="SQL, schema design, indexing and query optimisation.",
        subskills=["SQL queries", "Schema design", "Indexing", "Query optimisation"],
        what_you_get=["Confirmed level", "Score per subskill", "PDF report", "Learning pathway"],
    ),
    AssessmentDetail(
        test_id=208,
        title="Version Control (Git)",
        skill_id=8,
        skill_name="Version Control (Git)",
        levels=LEVELS[:3],
        format="fixed",
        question_count=15,
        duration_minutes=15,
        price_credits=1,
        role_ids=[101, 102],
        description="Branching, merging, pull requests and resolving conflicts.",
        subskills=["Branching", "Merging", "Pull requests"],
        what_you_get=["Confirmed level", "Score per subskill", "PDF report"],
    ),
]
TESTS_BY_ID = {test.test_id: test for test in TESTS}
SAMPLE_CREDITS_BALANCE = 3


def get_test(test_id: int) -> AssessmentDetail:
    test = TESTS_BY_ID.get(test_id)
    if test is None:
        raise NotFoundError(f"Test {test_id} not found. Sample tests: {sorted(TESTS_BY_ID)}")
    return test


# TEST CATALOGUE: every test, filterable by skill or role. Public. Taking a test is /attempts.
@router.get(
    "", response_model=ApiResponse[Page[AssessmentSummary]], openapi_extra=sample_route("empty")
)
async def list_tests(
    skill_id: int | None = None,
    role_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
):
    tests = [] if sc.empty else TESTS
    if skill_id is not None:
        tests = [t for t in tests if t.skill_id == skill_id]
    if role_id is not None:
        tests = [t for t in tests if role_id in t.role_ids]
    items = [AssessmentSummary(**t.model_dump()) for t in tests[offset : offset + limit]]
    return sample(
        Page[AssessmentSummary](items=items, total=len(tests), limit=limit, offset=offset)
    )


@router.get(
    "/{test_id}", response_model=ApiResponse[AssessmentDetail], openapi_extra=sample_route()
)
async def get_test_detail(test_id: int):
    return sample(get_test(test_id))


# CAN I START IT? Free tests always; paid tests need credits or a subscription.
# When can_start is false, starting the test will answer 402 payment_required (once payments exist).
@router.get(
    "/{test_id}/access",
    response_model=ApiResponse[AssessmentAccess],
    openapi_extra=sample_route(
        summary_note="Test 202 and 203 cost 2 credits and the sample balance is 3, so they can start; "
        "send `payment_required` to see the 402 error."
    ),
)
async def get_test_access(test_id: int, learner_id: int = Depends(sample_user)):
    test = get_test(test_id)
    if test.price_credits == 0:
        reason, can_start = "free", True
    elif SAMPLE_CREDITS_BALANCE >= test.price_credits:
        reason, can_start = "credits", True
    else:
        reason, can_start = "insufficient_credits", False
    return sample(
        AssessmentAccess(
            test_id=test_id,
            can_start=can_start,
            reason=reason,
            price_credits=test.price_credits,
            credits_balance=SAMPLE_CREDITS_BALANCE,
        )
    )
