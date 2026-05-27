"""Process library DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProcessCreate(BaseModel):
    process_id: Optional[str] = None
    process_code: str
    process_name: str
    process_type: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class ProcessUpdate(BaseModel):
    process_name: Optional[str] = None
    process_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ProcessResponse(ORMModel):
    process_id: str
    process_code: str
    process_name: str
    process_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = True
    created_at: Optional[datetime] = None
