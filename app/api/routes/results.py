from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_learner, get_db
from app.core.responses import EnvelopeRoute, errors
from app.models.models import Learner
from app.schemas.common import Page
from app.schemas.results import Report, ResultDetail, ResultSummary
from app.services.reports import (
    list_results,
    make_report_again,
    report_download,
    report_status,
    result_detail,
)

# Results are finished adaptive tests (Day 12): result_id is the attempt_id
router = APIRouter(prefix="/results", tags=["Results"], route_class=EnvelopeRoute)
# The download link of a ready report: the signed token in the path is the proof
downloads = APIRouter(prefix="/reports", tags=["Results"], route_class=EnvelopeRoute)


def _link_for(request: Request):
    def link(token: str) -> str:
        return str(request.url_for("download_result_report", token=token))

    return link


# MY RESULTS: my finished tests, newest first
@router.get("", response_model=Page[ResultSummary], responses=errors(401))
async def list_my_results(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await list_results(db, current_learner.learner_id, limit, offset)


# ONE RESULT IN DETAIL
@router.get(
    "/{result_id}",
    response_model=ResultDetail,
    responses=errors(401, 404),
    description="404: no finished test of yours with this id.",
)
async def get_result(
    result_id: int,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await result_detail(db, result_id, current_learner.learner_id)


# PDF REPORT: poll until status is "ready", then open download_url (a short-lived link)
@router.get(
    "/{result_id}/report",
    response_model=Report,
    responses=errors(401, 404),
    description="The first call starts making the PDF (status generating); poll every 2-3 s "
    "until ready, then open download_url (works without a token until expires_at; poll again "
    "for a fresh link). failed: ask again with POST.",
)
async def get_result_report(
    result_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await report_status(db, result_id, current_learner.learner_id, _link_for(request))


# Make the report again (e.g. after it failed); answers 202 with status "generating"
@router.post(
    "/{result_id}/report",
    status_code=202,
    response_model=Report,
    responses=errors(401, 404),
    description="Makes the PDF again (older download links stop working). Already being made: "
    "nothing new is started.",
)
async def regenerate_result_report(
    result_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    current_learner: Learner = Depends(get_current_learner),
):
    return await make_report_again(db, result_id, current_learner.learner_id, _link_for(request))


# DOWNLOAD A READY REPORT (the link from GET /results/{result_id}/report)
@downloads.get(
    "/{token}",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The PDF"},
        **errors(410),
    },
    description="The PDF itself, as an attachment. No login token: the link is the proof. "
    "410 expired: the link is too old, or the report was made again since.",
)
async def download_result_report(token: str, db: AsyncSession = Depends(get_db, scope="function")):
    pdf, filename = await report_download(db, token)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
