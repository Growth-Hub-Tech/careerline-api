from datetime import date

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, days_ago
from app.schemas.common import LevelName, Page
from app.schemas.organisations import (
    Audit,
    AuditCreate,
    AuditSummary,
    Benchmark,
    GroupBy,
    Heatmap,
    HeatmapCell,
    HeatmapRow,
    HeatmapSkill,
    Organisation,
    RosterResult,
    RosterUpload,
    Target,
    Targets,
    TargetsUpdate,
    TeamMember,
)

ORG_ID = 41
ORG_NOTE = (
    f"Organisation accounts don't exist yet: any login token works, the sample organisation is {ORG_ID}, "
    "and `forbidden` shows the 403 someone outside the organisation will get."
)

audit_router = APIRouter(
    prefix="/organisations",
    tags=["Sample: Organisation audit"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)
heatmap_router = APIRouter(
    prefix="/organisations",
    tags=["Sample: Heatmap"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)
targets_router = APIRouter(
    prefix="/organisations",
    tags=["Sample: Targets"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

ORGANISATION = Organisation(
    organisation_id=ORG_ID,
    name="Acme Fintech Ltd",
    industry="Financial services",
    size="51-200",
    seats_total=50,
    seats_used=12,
    created_at=days_ago(60),
)
ROLES = {101: "Frontend Developer", 102: "Backend Developer", 103: "Data Analyst"}
SKILLS = {1: "Frontend Web Development", 2: "Backend Development", 3: "Database Management"}

MEMBERS = [
    TeamMember(
        member_id=901,
        full_name="Ngozi Okeke",
        email="ngozi.okeke@example.com",
        department="Payments",
        role_id=102,
        role_title="Backend Developer",
        status="completed",
        latest_level=LevelName.MID,
    ),
    TeamMember(
        member_id=902,
        full_name="Emeka Obi",
        email="emeka.obi@example.com",
        department="Payments",
        role_id=101,
        role_title="Frontend Developer",
        status="completed",
        latest_level=LevelName.JUNIOR,
    ),
    TeamMember(
        member_id=903,
        full_name="Halima Sani",
        email="halima.sani@example.com",
        department="Lending",
        role_id=103,
        role_title="Data Analyst",
        status="in_progress",
        latest_level=None,
    ),
    TeamMember(
        member_id=904,
        full_name="David Johnson",
        email="david.johnson@example.com",
        department="Lending",
        role_id=102,
        role_title="Backend Developer",
        status="invited",
        latest_level=None,
    ),
]

BENCHMARKS = [
    Benchmark(
        role_id=102,
        role_title="Backend Developer",
        skill_id=2,
        skill_name="Backend Development",
        target_level=LevelName.MID,
        team_average_score=71.5,
        industry_average_score=66.0,
        members_at_or_above_target=1,
        members_tested=1,
    ),
    Benchmark(
        role_id=101,
        role_title="Frontend Developer",
        skill_id=1,
        skill_name="Frontend Web Development",
        target_level=LevelName.MID,
        team_average_score=58.0,
        industry_average_score=63.0,
        members_at_or_above_target=0,
        members_tested=1,
    ),
]

AUDIT = Audit(
    audit_id=1201,
    name="Q4 2026 engineering audit",
    status="in_progress",
    role_ids=[101, 102, 103],
    members_total=4,
    members_completed=2,
    started_at=days_ago(7),
    completed_at=None,
    benchmarks=BENCHMARKS,
)


def check_org(organisation_id: int) -> None:
    if organisation_id != ORG_ID:
        raise NotFoundError(
            f"Organisation {organisation_id} not found. The sample organisation is {ORG_ID}"
        )


# MY ORGANISATION
@audit_router.get(
    "/me",
    response_model=ApiResponse[Organisation],
    openapi_extra=sample_route(summary_note=ORG_NOTE),
)
async def get_my_organisation(learner_id: int = Depends(sample_user)):
    return sample(ORGANISATION)


# TEAM ROSTER: everyone mapped to a role (PRD 6.2 step 1)
@audit_router.get(
    "/{organisation_id}/members",
    response_model=ApiResponse[Page[TeamMember]],
    openapi_extra=sample_route("empty", summary_note=ORG_NOTE),
)
async def list_team_members(
    organisation_id: int,
    department: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    check_org(organisation_id)
    members = [] if sc.empty else MEMBERS
    if department:
        members = [m for m in members if m.department == department]
    return sample(
        Page[TeamMember](
            items=members[offset : offset + limit], total=len(members), limit=limit, offset=offset
        )
    )


# UPLOAD THE ROSTER: adds new people and updates existing ones (matched by email)
@audit_router.post(
    "/{organisation_id}/members",
    response_model=ApiResponse[RosterResult],
    openapi_extra=sample_route(
        summary_note=ORG_NOTE + " More people than seats is `payment_required` (402)."
    ),
)
async def upload_roster(
    organisation_id: int, data: RosterUpload, learner_id: int = Depends(sample_user)
):
    check_org(organisation_id)
    known = {m.email for m in MEMBERS}
    updated = sum(1 for m in data.members if m.email in known)
    added = len(data.members) - updated
    return sample(RosterResult(added=added, updated=updated, members_total=len(MEMBERS) + added))


# AUDITS: test the team for their roles, then compare against targets and the industry
@audit_router.get(
    "/{organisation_id}/audits",
    response_model=ApiResponse[Page[AuditSummary]],
    openapi_extra=sample_route("empty", summary_note=ORG_NOTE),
)
async def list_audits(
    organisation_id: int,
    limit: int = 20,
    offset: int = 0,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    check_org(organisation_id)
    audits = [] if sc.empty else [AuditSummary(**AUDIT.model_dump())]
    return sample(
        Page[AuditSummary](
            items=audits[offset : offset + limit], total=len(audits), limit=limit, offset=offset
        )
    )


@audit_router.post(
    "/{organisation_id}/audits",
    status_code=201,
    response_model=ApiResponse[Audit],
    openapi_extra=sample_route(
        summary_note=ORG_NOTE + " send_invitations=true emails everyone their test link."
    ),
)
async def start_audit(
    organisation_id: int, data: AuditCreate, learner_id: int = Depends(sample_user)
):
    check_org(organisation_id)
    members = [m for m in MEMBERS if m.role_id in data.role_ids]
    if data.member_ids is not None:
        members = [m for m in members if m.member_id in data.member_ids]
    return sample(
        Audit(
            audit_id=1202,
            name=data.name,
            status="in_progress" if data.send_invitations else "draft",
            role_ids=data.role_ids,
            members_total=len(members),
            members_completed=0,
            started_at=NOW if data.send_invitations else None,
            completed_at=None,
            benchmarks=[],
        )
    )


@audit_router.get(
    "/{organisation_id}/audits/{audit_id}",
    response_model=ApiResponse[Audit],
    openapi_extra=sample_route(summary_note=ORG_NOTE),
)
async def get_audit(organisation_id: int, audit_id: int, learner_id: int = Depends(sample_user)):
    check_org(organisation_id)
    if audit_id != AUDIT.audit_id:
        raise NotFoundError(f"Audit {audit_id} not found. The sample audit is {AUDIT.audit_id}")
    return sample(AUDIT)


def _cell(skill_id: int, score: float | None, tested: int) -> HeatmapCell:
    if score is None:
        return HeatmapCell(
            skill_id=skill_id, average_score=None, level=None, members_tested=0, band="not_tested"
        )
    level = (
        LevelName.MID if score >= 70 else LevelName.JUNIOR if score >= 50 else LevelName.BEGINNER
    )
    band = "strong" if score >= 70 else "developing" if score >= 50 else "weak"
    return HeatmapCell(
        skill_id=skill_id, average_score=score, level=level, members_tested=tested, band=band
    )


HEATMAP_ROWS: dict[str, list[HeatmapRow]] = {
    "department": [
        HeatmapRow(
            key="payments",
            label="Payments",
            members=2,
            cells=[_cell(1, 58.0, 1), _cell(2, 71.5, 1), _cell(3, 64.0, 2)],
        ),
        HeatmapRow(
            key="lending",
            label="Lending",
            members=2,
            cells=[_cell(1, None, 0), _cell(2, 44.0, 1), _cell(3, 52.0, 1)],
        ),
    ],
    "role": [
        HeatmapRow(
            key="101",
            label="Frontend Developer",
            members=1,
            cells=[_cell(1, 58.0, 1), _cell(2, None, 0), _cell(3, 40.0, 1)],
        ),
        HeatmapRow(
            key="102",
            label="Backend Developer",
            members=2,
            cells=[_cell(1, None, 0), _cell(2, 57.8, 2), _cell(3, 70.0, 2)],
        ),
        HeatmapRow(
            key="103",
            label="Data Analyst",
            members=1,
            cells=[_cell(1, None, 0), _cell(2, None, 0), _cell(3, 52.0, 1)],
        ),
    ],
    "member": [
        HeatmapRow(
            key="901",
            label="Ngozi Okeke",
            members=1,
            cells=[_cell(1, None, 0), _cell(2, 71.5, 1), _cell(3, 76.0, 1)],
        ),
        HeatmapRow(
            key="902",
            label="Emeka Obi",
            members=1,
            cells=[_cell(1, 58.0, 1), _cell(2, None, 0), _cell(3, 40.0, 1)],
        ),
    ],
}


# CAPABILITY HEATMAP: rows by department, role or person; columns are skills (PRD 6.2 step 3)
@heatmap_router.get(
    "/{organisation_id}/heatmap",
    response_model=ApiResponse[Heatmap],
    openapi_extra=sample_route("empty", summary_note=ORG_NOTE),
)
async def get_heatmap(
    organisation_id: int,
    group_by: GroupBy = "department",
    audit_id: int | None = None,
    sc: Scenario = Depends(scenario),
    learner_id: int = Depends(sample_user),
):
    check_org(organisation_id)
    return sample(
        Heatmap(
            organisation_id=organisation_id,
            audit_id=audit_id if audit_id is not None else AUDIT.audit_id,
            group_by=group_by,
            skills=[
                HeatmapSkill(skill_id=skill_id, skill_name=name)
                for skill_id, name in SKILLS.items()
            ],
            rows=[] if sc.empty else HEATMAP_ROWS[group_by],
        )
    )


TARGETS = [
    Target(
        role_id=102,
        role_title="Backend Developer",
        skill_id=2,
        skill_name="Backend Development",
        target_level=LevelName.MID,
        due_date=date(2027, 3, 31),
        members_total=2,
        members_meeting=1,
        progress_percent=50,
    ),
    Target(
        role_id=101,
        role_title="Frontend Developer",
        skill_id=1,
        skill_name="Frontend Web Development",
        target_level=LevelName.MID,
        due_date=date(2027, 3, 31),
        members_total=1,
        members_meeting=0,
        progress_percent=0,
    ),
]


# TARGETS: the level each role should reach in each skill, and progress towards it
@targets_router.get(
    "/{organisation_id}/targets",
    response_model=ApiResponse[Targets],
    openapi_extra=sample_route("empty", summary_note=ORG_NOTE),
)
async def get_targets(
    organisation_id: int, sc: Scenario = Depends(scenario), learner_id: int = Depends(sample_user)
):
    check_org(organisation_id)
    return sample(Targets(organisation_id=organisation_id, items=[] if sc.empty else TARGETS))


@targets_router.put(
    "/{organisation_id}/targets",
    response_model=ApiResponse[Targets],
    openapi_extra=sample_route(summary_note=ORG_NOTE + " Replaces all targets."),
)
async def set_targets(
    organisation_id: int, data: TargetsUpdate, learner_id: int = Depends(sample_user)
):
    check_org(organisation_id)
    members = {101: 1, 102: 2, 103: 1}
    items = [
        Target(
            role_id=item.role_id,
            role_title=ROLES.get(item.role_id, f"Role {item.role_id}"),
            skill_id=item.skill_id,
            skill_name=SKILLS.get(item.skill_id, f"Skill {item.skill_id}"),
            target_level=item.target_level,
            due_date=item.due_date,
            members_total=members.get(item.role_id, 0),
            members_meeting=0,
            progress_percent=0,
        )
        for item in data.items
    ]
    return sample(Targets(organisation_id=organisation_id, items=items))
