"""Submit landing-page contact enquiries via AWS SES (with log fallback)."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.schemas.contact import ContactEnquiryIn, ContactEnquiryOut

logger = logging.getLogger(__name__)


def _format_body(payload: ContactEnquiryIn) -> str:
    lines = [
        payload.message,
        "",
        f"Name: {payload.name}",
        f"Email: {payload.email}",
    ]
    if payload.organisation:
        lines.append(f"Organisation: {payload.organisation}")
    return "\n".join(lines)


def _send_via_ses(payload: ContactEnquiryIn) -> None:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("ses", region_name=settings.contact_aws_region)
    subject = f"Nyra Services enquiry from {payload.name}"
    body_text = _format_body(payload)

    try:
        client.send_email(
            Source=settings.contact_from_email,
            Destination={"ToAddresses": [settings.contact_to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            },
            ReplyToAddresses=[str(payload.email)],
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"SES send failed: {exc}") from exc


def submit_contact_enquiry(payload: ContactEnquiryIn) -> ContactEnquiryOut:
    if not settings.contact_enquiry_enabled:
        raise RuntimeError("Contact enquiries are not enabled on this server")

    body_text = _format_body(payload)
    logger.info(
        "Contact enquiry received name=%s email=%s organisation=%s message_len=%s",
        payload.name,
        payload.email,
        payload.organisation or "",
        len(payload.message),
    )

    if settings.contact_enquiry_dry_run:
        logger.info("Contact enquiry dry-run body:\n%s", body_text)
        return ContactEnquiryOut()

    if settings.contact_to_email and settings.contact_from_email:
        try:
            _send_via_ses(payload)
            return ContactEnquiryOut()
        except Exception as exc:
            logger.warning("Contact enquiry SES delivery failed: %s", exc)
            raise RuntimeError(
                "We received your message but could not deliver it by email. "
                "Please try again later or email us directly."
            ) from exc

    logger.info("Contact enquiry stored in server logs:\n%s", body_text)
    return ContactEnquiryOut()
