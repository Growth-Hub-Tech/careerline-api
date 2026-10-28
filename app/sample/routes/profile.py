from fastapi import APIRouter, Depends

from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, days_ago
from app.schemas.profile import Profile, ProfileUpdate

router = APIRouter(
    prefix="/profile",
    tags=["Sample: Profile"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)


def _profile(learner_id: int) -> Profile:
    return Profile(
        learner_id=learner_id,
        full_name="Ada Okafor",
        headline="Aspiring frontend developer",
        location="Lagos, Nigeria",
        current_role="Customer support associate",
        years_experience=2,
        goals=["Get a first tech job", "Build a portfolio"],
        weekly_hours=10,
        budget="under_50k",
        linkedin_url=None,
        visibility="private",
        completeness=80,
        updated_at=days_ago(1),
    )


# MY PROFILE: the one skill profile per person (PRD: shared with recruiters only if visible)
@router.get("", response_model=ApiResponse[Profile], openapi_extra=sample_route())
async def get_my_profile(learner_id: int = Depends(sample_user)):
    return sample(_profile(learner_id))


@router.patch("", response_model=ApiResponse[Profile], openapi_extra=sample_route())
async def update_my_profile(data: ProfileUpdate, learner_id: int = Depends(sample_user)):
    changes = data.model_dump(exclude_unset=True)
    return sample(_profile(learner_id).model_copy(update={**changes, "updated_at": NOW}))
