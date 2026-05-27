"""Feasibility DTOs."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class FeasibilityCheckResult(BaseModel):
    resource_type: str  # 'material' | 'machine' | 'tool' | 'workforce'
    status: str  # 'OK' | 'BLOCKED' | 'WARNING'
    detail: Optional[str] = None


class FeasibilityResponse(BaseModel):
    """Response of ``GET /feasibility/{lot_id}``.

    Built from the live availability tables (material, machine, tool,
    workforce, BOM) and persisted into ``trn.feasibility_gate``.
    """

    lot_id: str
    overall_status: str  # 'OK' | 'BLOCKED'
    material_status: Optional[str] = None
    machine_status: Optional[str] = None
    tool_status: Optional[str] = None
    workforce_status: Optional[str] = None
    blocked_reason: Optional[str] = None
    checked_at: Optional[datetime] = None
    checks: List[FeasibilityCheckResult] = []
