from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr

OrganisationRole = Literal["owner", "admin", "recruiter"]


class OrganisationUser(BaseModel):
    """An account of the organisation and its role (not the audit roster: see /members)."""

    learner_id: int
    full_name: str
    email: str
    role: OrganisationRole
    added_at: datetime


class OrganisationUserList(BaseModel):
    items: list[OrganisationUser]
    total: int


class OrganisationUserCreate(BaseModel):
    email: EmailStr  # an existing CareerLine account
    role: OrganisationRole


class OrganisationUserUpdate(BaseModel):
    role: OrganisationRole
