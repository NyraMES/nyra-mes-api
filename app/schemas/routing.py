"""Routing, operation, and operation-resource-requirement DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.data_capture import DataCaptureFormTemplate


class RoutingCreate(BaseModel):
    routing_id: Optional[str] = None
    part_id: str
    routing_version: Optional[str] = None
    process_type: Optional[str] = None
    is_active: bool = True


class RoutingOut(ORMModel):
    id: Optional[int] = None
    routing_id: str
    part_id: Optional[str] = None
    routing_version: Optional[str] = None
    process_type: Optional[str] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None


class RoutingOperationCreate(BaseModel):
    operation_id: Optional[str] = None
    routing_id: str
    operation_sequence: Optional[int] = None
    operation_name: str
    process_id: Optional[str] = None
    standard_cycle_time_minutes: Optional[Decimal] = None
    inspection_required: bool = False


class RoutingOperationOut(ORMModel):
    id: Optional[int] = None
    operation_id: str
    routing_operation_id: str
    operation_code: str
    routing_id: Optional[str] = None
    operation_sequence: int
    operation_name: str
    process_id: Optional[str] = None
    standard_cycle_time_minutes: Optional[Decimal] = None
    inspection_required: Optional[bool] = None
    created_at: Optional[datetime] = None
    suggested_next_operation_sequence: Optional[int] = None
    data_capture_templates: Optional[List[DataCaptureFormTemplate]] = None


class RoutingOperationEntryCreate(BaseModel):
    """Add an operation to a routing (``routing_id`` comes from the URL path)."""

    operation_id: Optional[str] = None
    operation_sequence: Optional[int] = None
    operation_name: str
    process_id: Optional[str] = None
    standard_cycle_time_minutes: Optional[Decimal] = None
    inspection_required: bool = False


class RoutingOperationUpdate(BaseModel):
    operation_sequence: Optional[int] = None
    operation_name: Optional[str] = None
    process_id: Optional[str] = None
    standard_cycle_time_minutes: Optional[Decimal] = None
    inspection_required: Optional[bool] = None


class PartRoutingOut(BaseModel):
    routing: RoutingOut
    operations: List["RoutingOperationOut"]


class OperationResourceRequirementCreate(BaseModel):
    operation_id: str
    required_resource_type: str  # 'material' | 'machine' | 'tool' | 'workforce'
    required_resource_id: int
    required_quantity: Optional[Decimal] = None
    is_mandatory: bool = True


class OperationResourceRequirementOut(ORMModel):
    id: Optional[int] = None
    operation_id: Optional[str] = None
    required_resource_type: Optional[str] = None
    required_resource_id: Optional[int] = None
    required_quantity: Optional[Decimal] = None
    is_mandatory: Optional[bool] = None
    created_at: Optional[datetime] = None


class _OperationInline(BaseModel):
    """An operation row inside a ``RoutingWithOperationsCreate`` payload.

    ``routing_id`` is filled in by the service after the parent routing has
    been inserted, so we don't accept it from the client here.
    """

    operation_id: Optional[str] = None
    operation_sequence: Optional[int] = None
    operation_name: str
    process_id: Optional[str] = None
    standard_cycle_time_minutes: Optional[Decimal] = None
    inspection_required: bool = False


class RoutingWithOperationsCreate(BaseModel):
    """Atomic create: ``Routing`` + N ``RoutingOperation`` in one POST."""

    routing_id: Optional[str] = None
    part_id: str
    routing_version: Optional[str] = None
    process_type: Optional[str] = None
    is_active: bool = True
    operations: List[_OperationInline] = []


class RoutingWithOperationsOut(BaseModel):
    routing: RoutingOut
    operations: List[RoutingOperationOut]
