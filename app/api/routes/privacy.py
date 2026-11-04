from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.privacy import (
    AccountDeletion,
    AccountDeletionRequest,
    Consents,
    ConsentUpdate,
    DataExport,
)
from app.services import privacy

# PRIVACY (Day 18, NDPR / GDPR): my consents, a copy of my data, and deleting my account
router = APIRouter(prefix="/privacy", tags=["Privacy"], route_class=EnvelopeRoute)


def _link_for(request: Request):
    def link(token: str) -> str:
        return str(request.url_for("download_data_export", token=token))

    return link


@router.get("/consents", response_model=Consents, responses=errors(401))
async def get_my_consents(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.my_consents(db, current_learner)


@router.put(
    "/consents",
    response_model=Consents,
    responses=errors(401, 422),
    description="Changes only the keys sent; every real change is kept with its time.",
)
async def update_my_consents(
    data: ConsentUpdate,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.update_consents(db, current_learner, data)


@router.post(
    "/data-exports",
    status_code=202,
    response_model=DataExport,
    responses=errors(401),
    description="Queues a copy of everything we hold about me (JSON). One at a time: while one "
    "is queued or ready, this answers that one. An email says when it is ready.",
)
async def request_data_export(
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.request_export(db, current_learner.learner_id, _link_for(request))


@router.get(
    "/data-exports/download/{token}",
    response_class=Response,
    responses={
        200: {"content": {"application/json": {}}, "description": "The JSON file"},
        **errors(410),
    },
    description="The file itself, as an attachment. No login token: the link is the proof. "
    "410 expired: the link is too old (it works 15 minutes) or the copy has expired.",
)
async def download_data_export(token: str, db: AsyncSession = Depends(get_db, scope="function")):
    content, filename = await privacy.export_download(db, token)
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/data-exports/{export_id}",
    response_model=DataExport,
    responses=errors(401, 404, 410),
    description="Poll until status is ready. download_url works 15 minutes: GET again for a "
    "fresh one. 410 expired: the copy is older than 7 days (ask for a new one).",
)
async def get_data_export(
    export_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.get_export(db, export_id, current_learner.learner_id, _link_for(request))


@router.post(
    "/account-deletion",
    status_code=202,
    response_model=AccountDeletion,
    responses=errors(400, 401, 422),
    description="Needs the password (400 wrong_password). Deletion happens 30 days later and "
    "can be cancelled until then; the account keeps working meanwhile. Asking again while one "
    "is scheduled answers that one.",
)
async def request_account_deletion(
    data: AccountDeletionRequest,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.request_deletion(db, current_learner, data)


@router.get(
    "/account-deletion",
    response_model=AccountDeletion,
    responses=errors(401, 404),
    description="My deletion request (scheduled or cancelled). 404: I never asked.",
)
async def get_account_deletion(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.deletion_status(db, current_learner.learner_id)


@router.delete(
    "/account-deletion",
    response_model=AccountDeletion,
    responses=errors(401, 404),
    description="Cancels a scheduled deletion. 404: nothing is scheduled.",
)
async def cancel_account_deletion(
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await privacy.cancel_deletion(db, current_learner.learner_id)
