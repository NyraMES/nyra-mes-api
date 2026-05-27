"""Shared schema primitives reused by multiple domain DTOs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base for any response model populated from a SQLAlchemy row."""

    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    """Generic ``{"message": ..., "id": ...}`` response."""

    message: str
    id: Optional[str] = None
    context: Optional[dict[str, Any]] = None
