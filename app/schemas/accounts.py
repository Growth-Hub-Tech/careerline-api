from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

AccountType = Literal["learner", "recruiter", "organisation_admin"]


class Account(BaseModel):
    account_id: int
    full_name: str
    email: EmailStr
    phone: str | None
    account_type: AccountType
    email_verified: bool
    organisation_id: int | None = None
    created_at: datetime


class AccountUpdate(BaseModel):
    """Send only the fields to change."""

    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class VerifyEmailRequest(BaseModel):
    token: str
