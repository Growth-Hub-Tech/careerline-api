from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, PROGRAMMES, PROGRAMMES_BY_ID
from app.schemas.common import Page
from app.schemas.programmes import (
    Programme,
    ProgrammeClick,
    ProgrammeClickRequest,
    ProgrammeSummary,
)

router = APIRouter(
    prefix="/programmes",
    tags=["Sample: Programmes"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)


def _get(programme_id: int) -> Programme:
    programme = PROGRAMMES_BY_ID.get(programme_id)
    if programme is None:
        raise NotFoundError(
            f"Programme {programme_id} not found. Sample programmes: {sorted(PROGRAMMES_BY_ID)}"
        )
    return programme


# PROGRAMMES: Incubate and partner courses that close a skill gap. Public.
@router.get(
    "", response_model=ApiResponse[Page[ProgrammeSummary]], openapi_extra=sample_route("empty")
)
async def list_programmes(
    role_id: int | None = None, limit: int = 20, offset: int = 0, sc: Scenario = Depends(scenario)
):
    programmes = [] if sc.empty else PROGRAMMES
    if role_id is not None:
        programmes = [p for p in programmes if role_id in p.role_ids]
    items = [ProgrammeSummary(**p.model_dump()) for p in programmes[offset : offset + limit]]
    return sample(
        Page[ProgrammeSummary](items=items, total=len(programmes), limit=limit, offset=offset)
    )


@router.get("/{programme_id}", response_model=ApiResponse[Programme], openapi_extra=sample_route())
async def get_programme(programme_id: int):
    return sample(_get(programme_id))


# PROGRAMME CLICK: record the click (for referral reporting), then send the person to redirect_url
@router.post(
    "/{programme_id}/clicks",
    status_code=201,
    response_model=ApiResponse[ProgrammeClick],
    openapi_extra=sample_route(),
)
async def record_programme_click(
    programme_id: int, data: ProgrammeClickRequest, learner_id: int = Depends(sample_user)
):
    programme = _get(programme_id)
    return sample(
        ProgrammeClick(
            click_id="clk_8f3a2c",
            programme_id=programme_id,
            redirect_url=f"{programme.url}?ref=careerline&click=clk_8f3a2c",
            clicked_at=NOW,
        )
    )
