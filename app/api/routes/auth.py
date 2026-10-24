from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_db
from app.core.responses import EnvelopeRoute, errors, ok
from app.schemas.auth import RegisterRequest, TokenResponse
from app.schemas.common import Acknowledgement
from app.services import account_service
from app.services.session_service import CurrentSession, revoke_all_sessions, revoke_session

# Create router for auth endpoints
router = APIRouter(prefix="/auth", tags=["Authentication"], route_class=EnvelopeRoute)

# Login answers with a standard OAuth2 token body (no envelope), so it has its own router
token_router = APIRouter(prefix="/auth", tags=["Authentication"])


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent")


# SIGN UP: creates the account, signs it in and emails a confirmation link
@router.post(
    "/register",
    responses=errors(400, 429),
    description="Creates the account and signs it in (the answer holds a token). A confirmation "
    "link is emailed; until it is opened, GET /accounts/me shows email_verified: false.",
)
async def register(
    data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db, scope="function")
):
    ip, user_agent = _client(request)
    result = await account_service.register(db, data, ip, user_agent)
    return ok(result, message=f"Learner {data.full_name} registered successfully")


# SIGN IN: the OAuth2 password form (username = email)
@token_router.post(
    "/login",
    response_model=TokenResponse,
    responses=errors(401, 422, 429),
    description="OAuth2 password form: username = email. A wrong password and an unknown email "
    "get the same 401. After 5 failed sign-ins for one email (or 20 from one IP address) in 15 "
    "minutes: 429 with Retry-After, whatever the password.",
)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    ip, user_agent = _client(request)
    return await account_service.login(db, form_data.username, form_data.password, ip, user_agent)


# SIGN OUT: ends this session (its token stops working at once), or every session
@router.post(
    "/logout",
    response_model=Acknowledgement,
    responses=errors(401),
    description="Ends this session: its token stops working at once. everywhere=true ends every "
    "session of the account (all devices).",
)
async def logout(
    everywhere: bool = Query(default=False, description="Sign out on every device"),
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    if everywhere:
        await revoke_all_sessions(db, current.learner.learner_id, "logout_everywhere")
    else:
        await revoke_session(db, current.session, "logout")
    return Acknowledgement()
