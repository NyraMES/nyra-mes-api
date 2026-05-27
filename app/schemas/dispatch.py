"""Dispatch and dispatch-line DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DispatchLineCreate(BaseModel):
    """Lines are keyed by lot + part; DB id is assigned on insert."""
    lot_id: str
    part_id: str
    dispatch_quantity: Decimal
    accepted_quantity: Optional[Decimal] = None
    rejected_quantity: Optional[Decimal] = 0


class DispatchLineOut(ORMModel):
    id: Optional[int] = None
    dispatch_line_id: Optional[int] = None
    dispatch_id: Optional[str] = None
    lot_id: Optional[str] = None
    part_id: Optional[str] = None
    dispatch_quantity: Optional[Decimal] = None
    accepted_quantity: Optional[Decimal] = None
    rejected_quantity: Optional[Decimal] = None
    created_at: Optional[datetime] = None


class DispatchCreate(BaseModel):
    dispatch_id: Optional[str] = None
    customer_id: str
    order_id: Optional[str] = None
    dispatch_date: Optional[datetime] = None
    vehicle_number: Optional[str] = None
    transporter_name: Optional[str] = None
    dispatch_status: Optional[str] = "Ready"
    remarks: Optional[str] = None
    lines: Optional[List[DispatchLineCreate]] = None


class DispatchOut(ORMModel):
    id: Optional[int] = None
    dispatch_id: str
    customer_id: Optional[str] = None
    order_id: Optional[str] = None
    dispatch_date: Optional[datetime] = None
    vehicle_number: Optional[str] = None
    transporter_name: Optional[str] = None
    dispatch_status: Optional[str] = None
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
