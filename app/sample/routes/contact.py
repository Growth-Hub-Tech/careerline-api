from fastapi import APIRouter, Depends

from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, sample, sample_route, scenario
from app.sample.data import NOW
from app.schemas.contact import ContactReceipt, ContactRequest

router = APIRouter(
    prefix="/contact",
    tags=["Sample: Contact"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)


# CONTACT FORM: public, no login. The real one emails the team and stores the message.
@router.post(
    "", status_code=201, response_model=ApiResponse[ContactReceipt], openapi_extra=sample_route()
)
async def send_contact_message(data: ContactRequest):
    return sample(ContactReceipt(ticket_id="CT-20261022-0042", status="received", received_at=NOW))
