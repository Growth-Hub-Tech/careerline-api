from pydantic import BaseModel


class RegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str
    password: str


#OAuth2 token response: kept at the top level (not in the envelope) so /docs "Authorize" and OAuth2 clients work
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    learner_id: int
    full_name: str
