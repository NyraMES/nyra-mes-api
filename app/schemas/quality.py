"""Quality DTOs: inspection results, parameter results, NCRs."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class InspectionResultCreate(BaseModel):
    inspection_id: Optional[str] = None
    work_order_id: Optional[str] = None
    lot_id: Optional[str] = None
    inspection_plan_id: Optional[str] = None
    inspected_quantity: Optional[Decimal] = None
    accepted_quantity: Optional[Decimal] = None
    rejected_quantity: Optional[Decimal] = None
    inspection_status: Optional[str] = "Pending"
    inspected_at: Optional[datetime] = None


class InspectionResultOut(ORMModel):
    id: Optional[int] = None
    inspection_id: str
    work_order_id: Optional[str] = None
    lot_id: Optional[str] = None
    inspection_plan_id: Optional[str] = None
    inspected_quantity: Optional[Decimal] = None
    accepted_quantity: Optional[Decimal] = None
    rejected_quantity: Optional[Decimal] = None
    inspection_status: Optional[str] = None
    inspected_at: Optional[datetime] = None


class InspectionParameterResultCreate(BaseModel):
    inspection_id: str
    parameter_id: int
    observed_value: Optional[Decimal] = None
    result_status: Optional[str] = None


class InspectionParameterResultOut(ORMModel):
    id: Optional[int] = None
    inspection_id: Optional[str] = None
    parameter_id: Optional[int] = None
    observed_value: Optional[Decimal] = None
    result_status: Optional[str] = None


class NCRCreate(BaseModel):
    ncr_id: Optional[str] = None
    inspection_id: Optional[str] = None
    defect_id: Optional[str] = None
    rejected_quantity: Optional[Decimal] = None
    disposition: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    status: Optional[str] = "Open"


class NCROut(ORMModel):
    id: Optional[int] = None
    ncr_id: str
    inspection_id: Optional[str] = None
    defect_id: Optional[str] = None
    rejected_quantity: Optional[Decimal] = None
    disposition: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
