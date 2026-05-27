"""Lightweight DTOs for resource pickers (machines, tools, materials, workforce).

These exist primarily to populate dropdowns in the Routing Master UI when
authoring ``operation_resource_requirement`` rows.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class WorkCenterOut(ORMModel):
    id: Optional[int] = None
    work_center_id: str
    work_center_name: str
    process_type: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None


class MachineOut(ORMModel):
    id: Optional[int] = None
    machine_id: str
    machine_name: str
    work_center_id: Optional[str] = None
    machine_type: Optional[str] = None
    machine_status: Optional[str] = None


class ToolOut(ORMModel):
    id: Optional[int] = None
    tool_id: str
    tool_name: str
    tool_type: Optional[str] = None
    tool_status: Optional[str] = None


class MaterialOut(ORMModel):
    id: Optional[int] = None
    material_id: str
    material_name: str
    material_type: Optional[str] = None
    unit_of_measure: Optional[str] = None
    available_quantity: Optional[Decimal] = None


class WorkforceRoleOut(ORMModel):
    id: Optional[int] = None
    role_id: str
    role_name: str
    skill_level: Optional[str] = None
    available_count: Optional[int] = None
    created_at: Optional[datetime] = None
