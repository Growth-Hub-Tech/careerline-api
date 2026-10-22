from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, days_ago
from app.schemas.common import LevelName, Page
from app.schemas.recruiter import Candidate, CandidateCreate, CandidateReport, CandidateTestResult

router = APIRouter(
    prefix="/recruiter",
    tags=["Sample: Recruiter"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

ROLE_NOTE = "Recruiter accounts don't exist yet: any login token works here; `forbidden` shows the 403 a learner will get."

RESULT_TOBI = CandidateTestResult(
    test_id=202,
    test_title="Backend Development",
    level=LevelName.MID,
    percentage_score=78.0,
    passed=True,
    completed_at=days_ago(1),
    result_id=511,
)

CANDIDATES = [
    Candidate(
        candidate_id=601,
        full_name="Tobi Adeyemi",
        email="tobi.adeyemi@example.com",
        role_id=102,
        role_title="Backend Developer",
        status="completed",
        added_at=days_ago(5),
        latest_result=RESULT_TOBI,
    ),
    Candidate(
        candidate_id=602,
        full_name="Chioma Eze",
        email="chioma.eze@example.com",
        role_id=101,
        role_title="Frontend Developer",
        status="in_progress",
        added_at=days_ago(3),
        latest_result=None,
    ),
    Candidate(
        candidate_id=603,
        full_name="Musa Bello",
        email="musa.bello@example.com",
        role_id=103,
        role_title="Data Analyst",
        status="invited",
        added_at=days_ago(1),
        latest_result=None,
    ),
]
CANDIDATES_BY_ID = {candidate.candidate_id: candidate for candidate in CANDIDATES}
ROLE_TITLES = {101: "Frontend Developer", 102: "Backend Developer", 103: "Data Analyst"}


def _get(candidate_id: int) -> Candidate:
    candidate = CANDIDATES_BY_ID.get(candidate_id)
    if candidate is None:
        raise NotFoundError(
            f"Candidate {candidate_id} not found. Sample candidates: {sorted(CANDIDATES_BY_ID)}"
        )
    return candidate


# MY CANDIDATES: filter by status; invite one with POST /invitations
@router.get(
    "/candidates",
    response_model=ApiResponse[Page[Candidate]],
    openapi_extra=sample_route("empty", summary_note=ROLE_NOTE),
)
async def list_candidates(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    candidates = [] if sc.empty else CANDIDATES
    if status:
        candidates = [c for c in candidates if c.status == status]
    return sample(
        Page[Candidate](
            items=candidates[offset : offset + limit],
            total=len(candidates),
            limit=limit,
            offset=offset,
        )
    )


@router.post(
    "/candidates",
    status_code=201,
    response_model=ApiResponse[Candidate],
    openapi_extra=sample_route(
        summary_note=ROLE_NOTE + " An email already added is a `conflict` (409)."
    ),
)
async def add_candidate(data: CandidateCreate, learner_id: int = Depends(sample_user)):
    return sample(
        Candidate(
            candidate_id=604,
            full_name=data.full_name,
            email=data.email,
            role_id=data.role_id,
            role_title=ROLE_TITLES.get(data.role_id) if data.role_id else None,
            status="added",
            added_at=NOW,
            latest_result=None,
        )
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=ApiResponse[Candidate],
    openapi_extra=sample_route(summary_note=ROLE_NOTE),
)
async def get_candidate(candidate_id: int, learner_id: int = Depends(sample_user)):
    return sample(_get(candidate_id))


# THE SCORED REPORT: only once the candidate has finished (404 before)
@router.get(
    "/candidates/{candidate_id}/report",
    response_model=ApiResponse[CandidateReport],
    openapi_extra=sample_route(summary_note=ROLE_NOTE + " Only candidate 601 has finished."),
)
async def get_candidate_report(candidate_id: int, learner_id: int = Depends(sample_user)):
    candidate = _get(candidate_id)
    if candidate.latest_result is None:
        raise NotFoundError(f"Candidate {candidate_id} has not finished a test yet")
    return sample(
        CandidateReport(
            candidate_id=candidate_id,
            full_name=candidate.full_name,
            role_title=candidate.role_title,
            fit="strong_fit",
            summary="Confirmed MID in Backend Development: strong on REST APIs and authentication, "
            "developing on query optimisation.",
            results=[candidate.latest_result],
            report_url=f"https://example.com/sample-reports/candidate-{candidate_id}.pdf",
        )
    )
