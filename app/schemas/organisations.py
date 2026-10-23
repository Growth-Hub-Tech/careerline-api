# Organisation audit (PRD 6.2): upload the team, test everyone for their role, then see
# benchmarks, a capability heatmap and progress against targets.
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import LevelName

MemberStatus = Literal["not_invited", "invited", "in_progress", "completed"]
AuditStatus = Literal["draft", "in_progress", "completed"]
GroupBy = Literal["department", "role", "member"]
CellBand = Literal["strong", "developing", "weak", "not_tested"]


class Organisation(BaseModel):
    organisation_id: int
    name: str
    industry: str | None
    size: str | None
    seats_total: int
    seats_used: int
    created_at: datetime


class TeamMember(BaseModel):
    member_id: int
    full_name: str
    email: EmailStr
    department: str | None
    role_id: int
    role_title: str
    status: MemberStatus
    latest_level: LevelName | None


class TeamMemberCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    department: str | None = Field(default=None, max_length=80)
    role_id: int


class RosterUpload(BaseModel):
    members: list[TeamMemberCreate] = Field(min_length=1, max_length=1000)


class RosterResult(BaseModel):
    added: int
    updated: int
    members_total: int


class Benchmark(BaseModel):
    role_id: int
    role_title: str
    skill_id: int
    skill_name: str
    target_level: LevelName
    team_average_score: float
    industry_average_score: float | None
    members_at_or_above_target: int
    members_tested: int


class AuditSummary(BaseModel):
    audit_id: int
    name: str
    status: AuditStatus
    role_ids: list[int]
    members_total: int
    members_completed: int
    started_at: datetime | None
    completed_at: datetime | None


class Audit(AuditSummary):
    benchmarks: list[Benchmark]


class AuditCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role_ids: list[int] = Field(min_length=1)
    member_ids: list[int] | None = Field(
        default=None, description="Default: everyone in those roles"
    )
    send_invitations: bool = True


class HeatmapSkill(BaseModel):
    skill_id: int
    skill_name: str


class HeatmapCell(BaseModel):
    skill_id: int
    average_score: float | None
    level: LevelName | None
    members_tested: int
    band: CellBand


class HeatmapRow(BaseModel):
    key: str
    label: str
    members: int
    cells: list[HeatmapCell]


class Heatmap(BaseModel):
    """Rows are departments, roles or people; columns are skills; cells are average scores."""

    organisation_id: int
    audit_id: int | None
    group_by: GroupBy
    skills: list[HeatmapSkill]
    rows: list[HeatmapRow]


class Target(BaseModel):
    role_id: int
    role_title: str
    skill_id: int
    skill_name: str
    target_level: LevelName
    due_date: date | None
    members_total: int
    members_meeting: int
    progress_percent: int = Field(ge=0, le=100)


class Targets(BaseModel):
    organisation_id: int
    items: list[Target]


class TargetSet(BaseModel):
    role_id: int
    skill_id: int
    target_level: LevelName
    due_date: date | None = None


class TargetsUpdate(BaseModel):
    """Replaces all targets of the organisation."""

    items: list[TargetSet]
