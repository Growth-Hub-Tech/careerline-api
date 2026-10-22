from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, scenario
from app.schemas.common import LevelName, Page
from app.schemas.roles import Role, RoleSkill, RoleSummary

router = APIRouter(
    prefix="/roles",
    tags=["Sample: Skills and roles"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

ROLES = [
    Role(
        role_id=101,
        title="Frontend Developer",
        slug="frontend-developer",
        track="tech",
        summary="Builds the screens people use, in the browser.",
        description="Turns designs into fast, accessible web pages with HTML, CSS, JavaScript and React.",
        skills=[
            RoleSkill(
                skill_id=1, skill_name="Frontend Web Development", target_level=LevelName.MID
            ),
            RoleSkill(
                skill_id=8, skill_name="Version Control (Git)", target_level=LevelName.JUNIOR
            ),
        ],
        test_ids=[201, 208],
    ),
    Role(
        role_id=102,
        title="Backend Developer",
        slug="backend-developer",
        track="tech",
        summary="Builds the APIs and data behind an app.",
        description="Designs REST APIs, authentication and databases, and keeps them fast and safe.",
        skills=[
            RoleSkill(skill_id=2, skill_name="Backend Development", target_level=LevelName.MID),
            RoleSkill(skill_id=3, skill_name="Database Management", target_level=LevelName.JUNIOR),
            RoleSkill(
                skill_id=8, skill_name="Version Control (Git)", target_level=LevelName.JUNIOR
            ),
        ],
        test_ids=[202, 203, 208],
    ),
    Role(
        role_id=103,
        title="Data Analyst",
        slug="data-analyst",
        track="tech",
        summary="Answers business questions with data.",
        description="Writes SQL, cleans data and turns it into reports people act on.",
        skills=[
            RoleSkill(skill_id=3, skill_name="Database Management", target_level=LevelName.MID)
        ],
        test_ids=[203],
    ),
]
ROLES_BY_ID = {role.role_id: role for role in ROLES}


# ROLE CATALOGUE: job roles and the skills (with target level) each one needs. Public.
@router.get("", response_model=ApiResponse[Page[RoleSummary]], openapi_extra=sample_route("empty"))
async def list_roles(limit: int = 20, offset: int = 0, sc: Scenario = Depends(scenario)):
    roles = [] if sc.empty else ROLES
    items = [RoleSummary(**role.model_dump()) for role in roles[offset : offset + limit]]
    return sample(Page[RoleSummary](items=items, total=len(roles), limit=limit, offset=offset))


@router.get("/{role_id}", response_model=ApiResponse[Role], openapi_extra=sample_route())
async def get_role(role_id: int):
    role = ROLES_BY_ID.get(role_id)
    if role is None:
        raise NotFoundError(f"Role {role_id} not found. Sample roles: {sorted(ROLES_BY_ID)}")
    return sample(role)
