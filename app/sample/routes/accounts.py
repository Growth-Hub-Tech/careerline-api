from fastapi import APIRouter, Depends

from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, sample, sample_route, sample_user, scenario
from app.sample.data import days_ago
from app.schemas.accounts import (
    Account,
    AccountUpdate,
    ChangePasswordRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    VerifyEmailRequest,
)
from app.schemas.common import Acknowledgement

router = APIRouter(
    prefix="/accounts",
    tags=["Sample: Accounts"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)


def _account(learner_id: int) -> Account:
    return Account(
        account_id=learner_id,
        full_name="Ada Okafor",
        email="ada.okafor@example.com",
        phone="+2348000000000",
        account_type="learner",
        email_verified=True,
        organisation_id=None,
        created_at=days_ago(30),
    )


# MY ACCOUNT: login details and account type (learner, recruiter or organisation admin)
@router.get("/me", response_model=ApiResponse[Account], openapi_extra=sample_route())
async def get_my_account(learner_id: int = Depends(sample_user)):
    return sample(_account(learner_id))


@router.patch("/me", response_model=ApiResponse[Account], openapi_extra=sample_route())
async def update_my_account(data: AccountUpdate, learner_id: int = Depends(sample_user)):
    return sample(_account(learner_id).model_copy(update=data.model_dump(exclude_unset=True)))


@router.post(
    "/me/password", response_model=ApiResponse[Acknowledgement], openapi_extra=sample_route()
)
async def change_my_password(data: ChangePasswordRequest, learner_id: int = Depends(sample_user)):
    return sample(Acknowledgement())


# PASSWORD RESET: always 202, whether or not the email has an account (no account guessing)
@router.post(
    "/password-reset",
    status_code=202,
    response_model=ApiResponse[Acknowledgement],
    openapi_extra=sample_route(),
)
async def request_password_reset(data: PasswordResetRequest):
    return sample(Acknowledgement())


@router.post(
    "/password-reset/confirm",
    response_model=ApiResponse[Acknowledgement],
    openapi_extra=sample_route(summary_note="An old or used token is `expired` (410)."),
)
async def confirm_password_reset(data: PasswordResetConfirm):
    return sample(Acknowledgement())


@router.post(
    "/verify-email",
    response_model=ApiResponse[Acknowledgement],
    openapi_extra=sample_route(summary_note="An old or used token is `expired` (410)."),
)
async def verify_email(data: VerifyEmailRequest):
    return sample(Acknowledgement())


@router.post(
    "/verify-email/resend",
    status_code=202,
    response_model=ApiResponse[Acknowledgement],
    openapi_extra=sample_route(),
)
async def resend_verification_email(learner_id: int = Depends(sample_user)):
    return sample(Acknowledgement())
