"""Maintenance and machine-downtime DTOs.

The DB tables for these are surrogate-only (no business code), so the
public ``id`` is just the bigint PK exposed as an integer.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class MaintenanceEventCreate(BaseModel):
    machine_id: str
    event_type: Optional[str] = None
    event_status: Optional[str] = "Reported"
    reported_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reported_by: Optional[str] = None
    issue_description: Optional[str] = None
    action_taken: Optional[str] = None
    downtime_minutes: Optional[Decimal] = None


class MaintenanceEventOut(ORMModel):
    id: Optional[int] = None
    machine_id: Optional[str] = None
    event_type: Optional[str] = None
    event_status: Optional[str] = None
    reported_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reported_by: Optional[str] = None
    issue_description: Optional[str] = None
    action_taken: Optional[str] = None
    downtime_minutes: Optional[Decimal] = None


class MachineDowntimeCreate(BaseModel):
    machine_id: str
    work_order_id: Optional[str] = None
    downtime_reason: Optional[str] = None
    downtime_start: Optional[datetime] = None
    downtime_end: Optional[datetime] = None
    downtime_minutes: Optional[Decimal] = None


class MachineDowntimeOut(ORMModel):
    id: Optional[int] = None
    machine_id: Optional[str] = None
    work_order_id: Optional[str] = None
    downtime_reason: Optional[str] = None
    downtime_start: Optional[datetime] = None
    downtime_end: Optional[datetime] = None
    downtime_minutes: Optional[Decimal] = None
    created_at: Optional[datetime] = None
