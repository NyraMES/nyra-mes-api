"""Auth request/response schemas."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class UserContextOut(BaseModel):
    sub: str
    username: str
    email: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)


class AuthConfigOut(BaseModel):
    auth_enabled: bool
    cognito_region: Optional[str] = None
    cognito_user_pool_id: Optional[str] = None
    cognito_app_client_id: Optional[str] = None
