from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    PHONE_MAX_LENGTH,
)


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=FULL_NAME_MAX_LENGTH)
    # Must look like an email (email-validator, no DNS lookup); the length is checked after that
    email: EmailStr = Field(max_length=EMAIL_MAX_LENGTH)
    phone: str = Field(max_length=PHONE_MAX_LENGTH)
    password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


# OAuth2 token response: kept at the top level (not in the envelope) so /docs "Authorize" and OAuth2 clients work
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    learner_id: int
    full_name: str
