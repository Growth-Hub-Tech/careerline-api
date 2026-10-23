from datetime import timedelta

from fastapi import APIRouter, Depends

from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, days_ago
from app.schemas.privacy import (
    AccountDeletion,
    AccountDeletionRequest,
    Consent,
    Consents,
    ConsentUpdate,
    DataExport,
)

router = APIRouter(
    prefix="/privacy",
    tags=["Sample: Privacy"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

CONSENTS = [
    Consent(key="marketing_emails", granted=False, updated_at=days_ago(30)),
    Consent(key="share_profile_with_recruiters", granted=True, updated_at=days_ago(2)),
    Consent(key="product_research", granted=False, updated_at=days_ago(30)),
]


# MY CONSENTS: what I agreed to; every change is recorded with its time
@router.get("/consents", response_model=ApiResponse[Consents], openapi_extra=sample_route())
async def get_my_consents(learner_id: int = Depends(sample_user)):
    return sample(Consents(items=CONSENTS))


@router.put("/consents", response_model=ApiResponse[Consents], openapi_extra=sample_route())
async def update_my_consents(data: ConsentUpdate, learner_id: int = Depends(sample_user)):
    changes = {change.key: change.granted for change in data.items}
    items = [
        consent.model_copy(update={"granted": changes[consent.key], "updated_at": NOW})
        if consent.key in changes
        else consent
        for consent in CONSENTS
    ]
    return sample(Consents(items=items))


def _export(status: str) -> DataExport:
    ready = status == "ready"
    return DataExport(
        export_id=4401,
        status="ready" if ready else "queued",
        requested_at=NOW - timedelta(minutes=5),
        download_url="https://example.com/sample-exports/4401.zip" if ready else None,
        expires_at=NOW + timedelta(days=7) if ready else None,
    )


# A COPY OF MY DATA: queued now, emailed and downloadable when ready
@router.post(
    "/data-exports",
    status_code=202,
    response_model=ApiResponse[DataExport],
    openapi_extra=sample_route(),
)
async def request_data_export(learner_id: int = Depends(sample_user)):
    return sample(_export("queued"))


@router.get(
    "/data-exports/{export_id}",
    response_model=ApiResponse[DataExport],
    openapi_extra=sample_route(
        "pending", summary_note="`expired` (410) means the download link expired."
    ),
)
async def get_data_export(
    export_id: int, sc: Scenario = Depends(scenario), learner_id: int = Depends(sample_user)
):
    return sample(_export("queued" if sc.name == "pending" else "ready"))


# DELETE MY ACCOUNT: needs the password; scheduled 30 days ahead so it can be cancelled
@router.post(
    "/account-deletion",
    status_code=202,
    response_model=ApiResponse[AccountDeletion],
    openapi_extra=sample_route(),
)
async def request_account_deletion(
    data: AccountDeletionRequest, learner_id: int = Depends(sample_user)
):
    return sample(
        AccountDeletion(
            status="scheduled", requested_at=NOW, scheduled_for=NOW + timedelta(days=30)
        )
    )


@router.delete(
    "/account-deletion", response_model=ApiResponse[AccountDeletion], openapi_extra=sample_route()
)
async def cancel_account_deletion(learner_id: int = Depends(sample_user)):
    return sample(AccountDeletion(status="cancelled", requested_at=NOW, scheduled_for=None))
