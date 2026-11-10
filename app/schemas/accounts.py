from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import FULL_NAME_MAX_LENGTH, PASSWORD_MAX_LENGTH, PHONE_MAX_LENGTH

AccountType = Literal["learner", "recruiter", "organisation_admin"]


class Account(BaseModel):
    account_id: int
    full_name: str
    email: EmailStr
    phone: str | None
    account_type: AccountType
    email_verified: bool
    organisation_id: int | None = None
    organisation_role: Literal["owner", "admin", "recruiter"] | None = Field(
        default=None,
        description="The role in organisation_id (owner and admin = organisation_admin)",
    )
    created_at: datetime


class AccountUpdate(BaseModel):
    """Send only the fields to change."""

    full_name: str | None = Field(default=None, min_length=1, max_length=FULL_NAME_MAX_LENGTH)
    phone: str | None = Field(default=None, max_length=PHONE_MAX_LENGTH)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


class VerifyEmailRequest(BaseModel):
    token: str
