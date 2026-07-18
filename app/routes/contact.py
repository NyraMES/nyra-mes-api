"""Public contact form — no authentication required."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.openapi_tags import Tags
from app.schemas.contact import ContactEnquiryIn, ContactEnquiryOut
from app.services import contact_enquiry_service

router = APIRouter(tags=[Tags.AUTH])


def _submit_contact_enquiry(payload: ContactEnquiryIn) -> ContactEnquiryOut:
    if not settings.contact_enquiry_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact form is not configured on this server",
        )
    try:
        return contact_enquiry_service.submit_contact_enquiry(payload)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/public/contact-enquiry",
    response_model=ContactEnquiryOut,
    summary="Submit landing-page contact enquiry",
)
def submit_contact_enquiry(payload: ContactEnquiryIn) -> ContactEnquiryOut:
    return _submit_contact_enquiry(payload)


@router.post(
    "/api/public/contact-enquiry",
    response_model=ContactEnquiryOut,
    summary="Submit landing-page contact enquiry (testbed nginx /api prefix)",
    include_in_schema=False,
)
def submit_contact_enquiry_via_api_prefix(payload: ContactEnquiryIn) -> ContactEnquiryOut:
    return _submit_contact_enquiry(payload)
