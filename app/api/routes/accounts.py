"""My account, email confirmation and password reset (Day 6: real, same contract as the sample)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.accounts import (
    Account,
    AccountUpdate,
    ChangePasswordRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    VerifyEmailRequest,
)
from app.schemas.common import Acknowledgement
from app.services import account_service
from app.services.session_service import CurrentSession

router = APIRouter(prefix="/accounts", tags=["Accounts"], route_class=EnvelopeRoute)


def account_of(learner: Learner) -> Account:
    return Account(
        account_id=learner.learner_id,
        full_name=learner.full_name,
        email=learner.email,
        phone=learner.phone_number,
        account_type="learner",
        email_verified=learner.email_verified_at is not None,
        organisation_id=None,
        created_at=learner.created_at,
    )


# MY ACCOUNT: login details and account type (learner, recruiter or organisation admin)
@router.get("/me", response_model=Account, responses=errors(401))
async def get_my_account(current: CurrentSession = Depends(get_current_session)):
    return account_of(current.learner)


@router.patch("/me", response_model=Account, responses=errors(401))
async def update_my_account(
    data: AccountUpdate,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    learner = current.learner
    changes = data.model_dump(exclude_unset=True)
    if changes.get("full_name"):
        learner.full_name = changes["full_name"]
    if "phone" in changes:
        learner.phone_number = changes["phone"]
    await db.flush()
    return account_of(learner)


@router.post(
    "/me/password",
    response_model=Acknowledgement,
    responses=errors(400, 401),
    description="Needs the current password (400 wrong_password otherwise). Signs out every "
    "other device; this session stays signed in. An email tells the owner.",
)
async def change_my_password(
    data: ChangePasswordRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    await account_service.change_password(
        db, current.learner, current.session.id, data.current_password, data.new_password
    )
    return Acknowledgement()


# PASSWORD RESET: always 202, whether or not the email has an account (no account guessing)
@router.post(
    "/password-reset",
    status_code=202,
    response_model=Acknowledgement,
    description="Always 202, whether or not the email has an account. If it has one, a reset "
    "link (valid 60 minutes, once) is emailed.",
)
async def request_password_reset(
    data: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    ip = request.client.host if request.client else None
    await account_service.request_password_reset(db, str(data.email), ip)
    return Acknowledgement()


@router.post(
    "/password-reset/confirm",
    response_model=Acknowledgement,
    responses=errors(410),
    description="Sets the new password and signs out every device. An old, used or unknown "
    "token is `expired` (410).",
)
async def confirm_password_reset(
    data: PasswordResetConfirm, db: AsyncSession = Depends(get_db, scope="function")
):
    await account_service.reset_password(db, data.token, data.new_password)
    return Acknowledgement()


@router.post(
    "/verify-email",
    response_model=Acknowledgement,
    responses=errors(410),
    description="The token from the confirmation link. An old, used or unknown token is "
    "`expired` (410).",
)
async def verify_email(
    data: VerifyEmailRequest, db: AsyncSession = Depends(get_db, scope="function")
):
    await account_service.verify_email(db, data.token)
    return Acknowledgement()


@router.post(
    "/verify-email/resend",
    status_code=202,
    response_model=Acknowledgement,
    responses=errors(401, 429),
    description="Emails a new confirmation link (the old one stops working). Nothing is sent if "
    "the email is already confirmed. At most 3 an hour.",
)
async def resend_verification_email(
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    await account_service.resend_verification(db, current.learner)
    return Acknowledgement()
