"""Public contact enquiry schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ContactEnquiryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    organisation: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=4000)


class ContactEnquiryOut(BaseModel):
    ok: bool = True
    message: str = "Thank you — your message has been received. We will get back to you soon."
