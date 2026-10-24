from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import EnvelopeRoute, errors
from app.db.session import get_db
from app.schemas.contact import ContactReceipt, ContactRequest
from app.services.contact_service import submit_contact_message

router = APIRouter(prefix="/contact", tags=["Contact"], route_class=EnvelopeRoute)


# CONTACT FORM: public, no login. Stores the message, emails the team and thanks the sender.
@router.post(
    "",
    status_code=201,
    response_model=ContactReceipt,
    responses=errors(422, 429),
    description="Public, no login. Stores the message and emails the team (who can reply "
    "straight to the sender) and an acknowledgement to the sender. At most 5 messages an hour "
    "per email address and per IP address (then 429 with Retry-After).",
)
async def send_contact_message(
    data: ContactRequest, request: Request, db: AsyncSession = Depends(get_db, scope="function")
):
    client_ip = request.client.host if request.client else None
    return await submit_contact_message(db, data, client_ip)
