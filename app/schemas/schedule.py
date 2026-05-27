"""Schedule and work-order DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ScheduleCreate(BaseModel):
    schedule_id: Optional[str] = None
    lot_id: str
    operation_id: Optional[str] = None
    planned_start_time: Optional[datetime] = None
    planned_end_time: Optional[datetime] = None
    assigned_work_center_id: Optional[str] = None
    assigned_machine_id: Optional[str] = None
    schedule_status: Optional[str] = "Scheduled"


class ScheduleOut(ORMModel):
    id: Optional[int] = None
    schedule_id: str
    lot_id: Optional[str] = None
    operation_id: Optional[str] = None
    planned_start_time: Optional[datetime] = None
    planned_end_time: Optional[datetime] = None
    assigned_work_center_id: Optional[str] = None
    assigned_machine_id: Optional[str] = None
    schedule_status: Optional[str] = None
    created_at: Optional[datetime] = None


class WorkOrderCreate(BaseModel):
    work_order_id: Optional[str] = None
    schedule_id: Optional[str] = None
    lot_id: str
    operation_id: Optional[str] = None
    work_order_status: Optional[str] = "Released"


class WorkOrderCompleteRequest(BaseModel):
    actual_output_quantity: Optional[Decimal] = None
    scrap_quantity: Optional[Decimal] = None
    rework_quantity: Optional[Decimal] = None
    operator_name: Optional[str] = None
    machine_id: Optional[str] = None
    downtime_minutes: Optional[Decimal] = None
    remarks: Optional[str] = None


class WorkOrderStartRequest(BaseModel):
    operator_name: Optional[str] = None


class WorkOrderHoldRequest(BaseModel):
    reason: str


class WorkOrderOut(ORMModel):
    id: Optional[int] = None
    work_order_id: str
    schedule_id: Optional[str] = None
    lot_id: Optional[str] = None
    operation_id: Optional[str] = None
    work_order_status: Optional[str] = None
    released_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    actual_output_quantity: Optional[Decimal] = None
    scrap_quantity: Optional[Decimal] = None
    rework_quantity: Optional[Decimal] = None
    operator_name: Optional[str] = None
    actual_machine_id: Optional[str] = None
    downtime_minutes: Optional[Decimal] = None
