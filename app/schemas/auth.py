from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr  # must look like an email (checked by email-validator, no DNS lookup)
    phone: str
    password: str = Field(min_length=8)


# OAuth2 token response: kept at the top level (not in the envelope) so /docs "Authorize" and OAuth2 clients work
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    learner_id: int
    full_name: str
