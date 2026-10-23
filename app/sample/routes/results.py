from typing import cast

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, days_ago
from app.schemas.common import LevelName, Page
from app.schemas.results import (
    Report,
    ReportStatus,
    ResultDetail,
    ResultRecommendation,
    ResultSummary,
    SubskillScore,
)

router = APIRouter(
    prefix="/results",
    tags=["Sample: Results"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

RESULTS = [
    ResultDetail(
        result_id=501,
        attempt_id=9001,
        test_id=201,
        skill_id=1,
        skill_name="Frontend Web Development",
        level=LevelName.JUNIOR,
        declared_level=LevelName.MID,
        percentage_score=64.0,
        passed=True,
        completed_at=days_ago(2),
        percentile=58,
        subskills=[
            SubskillScore(
                subskill_id=11, subskill_name="HTML semantics", percentage_score=88.0, band="strong"
            ),
            SubskillScore(
                subskill_id=12, subskill_name="CSS layout", percentage_score=72.0, band="strong"
            ),
            SubskillScore(
                subskill_id=13,
                subskill_name="JavaScript fundamentals",
                percentage_score=56.0,
                band="developing",
            ),
            SubskillScore(
                subskill_id=14, subskill_name="React", percentage_score=40.0, band="weak"
            ),
        ],
        strengths=["HTML semantics", "CSS layout"],
        gaps=["React"],
        recommendations=[
            ResultRecommendation(
                subskill_name="React",
                text="Build two small apps with state and effects, then learn lifting state up.",
                programme_id=301,
            ),
            ResultRecommendation(
                subskill_name="JavaScript fundamentals",
                text="Practise array methods, closures and async/await with short daily exercises.",
                programme_id=None,
            ),
        ],
    ),
    ResultDetail(
        result_id=502,
        attempt_id=9002,
        test_id=203,
        skill_id=3,
        skill_name="Database Management",
        level=LevelName.BEGINNER,
        declared_level=LevelName.JUNIOR,
        percentage_score=41.0,
        passed=False,
        completed_at=days_ago(9),
        percentile=31,
        subskills=[
            SubskillScore(
                subskill_id=31,
                subskill_name="SQL queries",
                percentage_score=60.0,
                band="developing",
            ),
            SubskillScore(
                subskill_id=32, subskill_name="Schema design", percentage_score=35.0, band="weak"
            ),
            SubskillScore(
                subskill_id=33, subskill_name="Indexing", percentage_score=28.0, band="weak"
            ),
        ],
        strengths=[],
        gaps=["Schema design", "Indexing"],
        recommendations=[
            ResultRecommendation(
                subskill_name="Schema design",
                text="Model three small apps on paper first: tables, keys and relationships.",
                programme_id=303,
            ),
        ],
    ),
]
RESULTS_BY_ID = {result.result_id: result for result in RESULTS}


def _get(result_id: int) -> ResultDetail:
    result = RESULTS_BY_ID.get(result_id)
    if result is None:
        raise NotFoundError(
            f"Result {result_id} not found. Sample results: {sorted(RESULTS_BY_ID)}"
        )
    return result


# MY RESULTS: newest first
@router.get(
    "", response_model=ApiResponse[Page[ResultSummary]], openapi_extra=sample_route("empty")
)
async def list_my_results(
    limit: int = 20,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    results = [] if sc.empty else RESULTS
    items = [ResultSummary(**r.model_dump()) for r in results[offset : offset + limit]]
    return sample(Page[ResultSummary](items=items, total=len(results), limit=limit, offset=offset))


@router.get("/{result_id}", response_model=ApiResponse[ResultDetail], openapi_extra=sample_route())
async def get_result(result_id: int, learner_id: int = Depends(sample_user)):
    return sample(_get(result_id))


def _report(result_id: int, status: ReportStatus) -> Report:
    if status == "ready":
        return Report(
            result_id=result_id,
            status="ready",
            download_url=f"https://example.com/sample-reports/result-{result_id}.pdf",
            expires_at=NOW.replace(hour=10),
            generated_at=NOW,
        )
    return Report(
        result_id=result_id, status=status, download_url=None, expires_at=None, generated_at=None
    )


# PDF REPORT: poll until status is "ready", then open download_url (a short-lived link)
@router.get(
    "/{result_id}/report",
    response_model=ApiResponse[Report],
    openapi_extra=sample_route("generating", "failed"),
)
async def get_result_report(
    result_id: int, sc: Scenario = Depends(scenario), learner_id: int = Depends(sample_user)
):
    _get(result_id)
    return sample(_report(result_id, cast(ReportStatus, sc.name or "ready")))


# Ask for the report to be made again (e.g. after it failed); answers 202 with status "generating"
@router.post(
    "/{result_id}/report",
    status_code=202,
    response_model=ApiResponse[Report],
    openapi_extra=sample_route(),
)
async def regenerate_result_report(result_id: int, learner_id: int = Depends(sample_user)):
    _get(result_id)
    return sample(_report(result_id, "generating"))
