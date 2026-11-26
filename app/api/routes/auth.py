from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_db
from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.core.rate_limit import client_ip
from app.core.responses import EnvelopeRoute, errors, ok
from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES, SESSION_COOKIE
from app.schemas.auth import RegisterRequest, TokenResponse
from app.schemas.common import Acknowledgement
from app.services import account_service
from app.services.session_service import CurrentSession, revoke_all_sessions, revoke_session

router = APIRouter(prefix="/auth", tags=["Authentication"], route_class=EnvelopeRoute)

# Login answers with a standard OAuth2 token body (no envelope), so it has its own router
token_router = APIRouter(prefix="/auth", tags=["Authentication"])


def _client(request: Request) -> tuple[str | None, str | None]:
    """Who is signing in. A browser on another site is refused: it could sign the visitor in
    to an account of the attacker's choosing (login CSRF). Clients that send no Origin pass."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in set(settings.CORS_ORIGINS):
        raise ForbiddenError("Sign in from the CareerLine website")
    return client_ip(request), request.headers.get("user-agent")


# The website's copy of the token: HttpOnly (page scripts cannot read it), Secure, as long-lived
# as the token itself. Delete it with the same attributes, or the browser keeps it.
def _cookie_attributes() -> dict:
    return {
        "path": "/",
        "secure": True,
        "httponly": True,
        "samesite": settings.SESSION_COOKIE_SAMESITE,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, **_cookie_attributes()
    )


@router.post(
    "/register",
    responses=errors(400, 403, 429),
    description="Creates the account and signs it in: the answer holds a token and the "
    f"{SESSION_COOKIE} cookie is set. A taken email is 400 email_taken.",
)
async def register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    ip, user_agent = _client(request)
    result = await account_service.register(db, data, ip, user_agent)
    _set_session_cookie(response, result["access_token"])
    return ok(result, message=f"Learner {data.full_name} registered successfully")


@token_router.post(
    "/login",
    response_model=TokenResponse,
    responses=errors(401, 403, 422, 429),
    description="OAuth2 password form: username = email. A wrong password and an unknown email "
    "get the same 401. After 5 failed sign-ins for one email (or 20 from one IP address) in 15 "
    "minutes: 429 with Retry-After, whatever the password. Also sets the token in the HttpOnly "
    f"{SESSION_COOKIE} cookie for the website (send requests with credentials; a cookie counts "
    "on a POST, PUT, PATCH or DELETE only with an Origin listed in CORS_ORIGINS).",
)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    ip, user_agent = _client(request)
    result = await account_service.login(db, form_data.username, form_data.password, ip, user_agent)
    _set_session_cookie(response, result["access_token"])
    return result


@router.post(
    "/logout",
    response_model=Acknowledgement,
    responses=errors(401),
    description="Ends this session: its token stops working at once, and the session cookie is "
    "deleted. everywhere=true ends every session of the account (all devices).",
)
async def logout(
    response: Response,
    everywhere: bool = Query(default=False, description="Sign out on every device"),
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    if everywhere:
        await revoke_all_sessions(db, current.learner.learner_id, "logout_everywhere")
    else:
        await revoke_session(db, current.session, "logout")
    response.delete_cookie(SESSION_COOKIE, **_cookie_attributes())
    return Acknowledgement()
