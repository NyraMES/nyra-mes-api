"""Part DTOs (business code exposed as ``part_id``)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class PartCreate(BaseModel):
    part_id: Optional[str] = None
    part_name: str
    part_type: Optional[str] = None
    unit_of_measure: Optional[str] = None


class PartOut(ORMModel):
    id: Optional[int] = None
    part_id: str
    part_name: str
    part_type: Optional[str] = None
    unit_of_measure: Optional[str] = None
    created_at: Optional[datetime] = None
