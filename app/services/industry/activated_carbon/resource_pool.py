"""Claim and release plant resources (kiln, labor pool, tools) during shop-floor execution."""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import Equipment, OperationExecution, Resource
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.routing_helpers import is_resource_available

_IN_USE_STATUS = "IN_USE"
_AVAILABLE_STATUS = "AVAILABLE"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _meta(row: OperationExecution) -> dict[str, Any]:
    data = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return dict(data)


def _labor_headcount(resource: Resource) -> float:
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    for key in ("operators", "headcount", "available_count", "capacity"):
        if meta.get(key) is not None:
            try:
                return max(float(meta[key]), 0.0)
            except (TypeError, ValueError):
                continue
    return 1.0


def _find_equipment(repo: TenantRepository, code: str) -> Optional[Equipment]:
    normalized = (code or "").strip()
    if not normalized:
        return None
    return (
        repo.query(Equipment)
        .filter(Equipment.equipment_code == normalized)
        .first()
    )


def _find_resource(repo: TenantRepository, code: str) -> Optional[Resource]:
    normalized = (code or "").strip()
    if not normalized:
        return None
    return (
        repo.query(Resource)
        .filter(Resource.resource_code == normalized)
        .first()
    )


def _resource_for_machine(
    repo: TenantRepository, machine_code: str
) -> tuple[Optional[Equipment], Optional[Resource]]:
    equipment = _find_equipment(repo, machine_code)
    resource = None
    if equipment and equipment.resource_id:
        resource = repo.get_by_pk(Resource, Resource.resource_id, equipment.resource_id)
    if not resource:
        resource = _find_resource(repo, machine_code)
    return equipment, resource


def _claim_record(
    *,
    kind: str,
    code: str,
    equipment_id: Optional[UUID] = None,
    resource_id: Optional[UUID] = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "code": code,
        "equipment_id": str(equipment_id) if equipment_id else None,
        "resource_id": str(resource_id) if resource_id else None,
    }


def _mark_machine_in_use(
    repo: TenantRepository,
    machine_code: str,
    *,
    execution_code: str,
    lot_code: str,
) -> Optional[dict[str, Any]]:
    equipment, resource = _resource_for_machine(repo, machine_code)
    if not equipment and not resource:
        return None
    stamp = {
        "active_execution_code": execution_code,
        "active_lot_code": lot_code,
    }
    if equipment:
        emeta = equipment.metadata_ if isinstance(equipment.metadata_, dict) else {}
        equipment.metadata_ = {**emeta, **stamp}
        equipment.status = _IN_USE_STATUS
    if resource:
        rmeta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
        resource.metadata_ = {**rmeta, **stamp}
        resource.status = _IN_USE_STATUS
    return _claim_record(
        kind="machine",
        code=machine_code,
        equipment_id=equipment.equipment_id if equipment else None,
        resource_id=resource.resource_id if resource else None,
    )


def _mark_labor_in_use(
    repo: TenantRepository,
    labor_code: str,
    *,
    execution_code: str,
    lot_code: str,
) -> Optional[dict[str, Any]]:
    resource = _find_resource(repo, labor_code)
    if not resource or (resource.resource_type or "").upper() != "LABOR":
        return None
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    in_use = int(meta.get("in_use_count") or 0) + 1
    capacity = _labor_headcount(resource)
    meta = {
        **meta,
        "in_use_count": in_use,
        "active_execution_code": execution_code,
        "active_lot_code": lot_code,
    }
    resource.metadata_ = meta
    if capacity > 0 and in_use >= capacity:
        resource.status = _IN_USE_STATUS
    return _claim_record(
        kind="labor",
        code=labor_code,
        resource_id=resource.resource_id,
    )


def _mark_tool_in_use(
    repo: TenantRepository,
    tool_code: str,
    *,
    execution_code: str,
    lot_code: str,
) -> Optional[dict[str, Any]]:
    resource = _find_resource(repo, tool_code)
    if not resource:
        return None
    rtype = (resource.resource_type or "").upper()
    if rtype not in ("TOOL", "MACHINE", "WORKCELL"):
        return None
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    resource.metadata_ = {
        **meta,
        "active_execution_code": execution_code,
        "active_lot_code": lot_code,
    }
    resource.status = _IN_USE_STATUS
    return _claim_record(kind="tool", code=tool_code, resource_id=resource.resource_id)


def _release_machine(repo: TenantRepository, record: dict[str, Any]) -> None:
    equipment = None
    resource = None
    if record.get("equipment_id"):
        try:
            equipment = repo.get_by_pk(
                Equipment, Equipment.equipment_id, UUID(str(record["equipment_id"]))
            )
        except (TypeError, ValueError):
            equipment = None
    if record.get("resource_id"):
        try:
            resource = repo.get_by_pk(
                Resource, Resource.resource_id, UUID(str(record["resource_id"]))
            )
        except (TypeError, ValueError):
            resource = None
    if not resource and record.get("code"):
        _, resource = _resource_for_machine(repo, str(record["code"]))
    if equipment:
        emeta = equipment.metadata_ if isinstance(equipment.metadata_, dict) else {}
        emeta.pop("active_execution_code", None)
        emeta.pop("active_lot_code", None)
        equipment.metadata_ = emeta
        equipment.status = _AVAILABLE_STATUS
    if resource:
        rmeta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
        rmeta.pop("active_execution_code", None)
        rmeta.pop("active_lot_code", None)
        resource.metadata_ = rmeta
        if is_resource_available(resource.status) or resource.status == _IN_USE_STATUS:
            resource.status = _AVAILABLE_STATUS


def _release_labor(repo: TenantRepository, record: dict[str, Any]) -> None:
    resource = None
    if record.get("resource_id"):
        try:
            resource = repo.get_by_pk(
                Resource, Resource.resource_id, UUID(str(record["resource_id"]))
            )
        except (TypeError, ValueError):
            resource = None
    if not resource and record.get("code"):
        resource = _find_resource(repo, str(record["code"]))
    if not resource:
        return
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    in_use = max(int(meta.get("in_use_count") or 0) - 1, 0)
    meta["in_use_count"] = in_use
    if in_use <= 0:
        meta.pop("active_execution_code", None)
        meta.pop("active_lot_code", None)
    capacity = _labor_headcount(resource)
    resource.metadata_ = meta
    if in_use <= 0 or (capacity > 0 and in_use < capacity):
        resource.status = _AVAILABLE_STATUS


def _release_tool(repo: TenantRepository, record: dict[str, Any]) -> None:
    resource = None
    if record.get("resource_id"):
        try:
            resource = repo.get_by_pk(
                Resource, Resource.resource_id, UUID(str(record["resource_id"]))
            )
        except (TypeError, ValueError):
            resource = None
    if not resource and record.get("code"):
        resource = _find_resource(repo, str(record["code"]))
    if not resource:
        return
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    meta.pop("active_execution_code", None)
    meta.pop("active_lot_code", None)
    resource.metadata_ = meta
    resource.status = _AVAILABLE_STATUS


def claim_execution_resources(
    db: Session, tenant: TenantContext, row: OperationExecution, *, lot_code: str
) -> None:
    """Mark kiln / crew / tools as in use when an operation starts."""
    repo = _repo(db, tenant)
    meta = _meta(row)
    if meta.get("resources_claimed"):
        return

    execution_code = row.execution_code
    claimed: List[dict[str, Any]] = []
    machine_code = (meta.get("actual_machine_code") or meta.get("assigned_machine_code") or "").strip()
    if machine_code:
        rec = _mark_machine_in_use(
            repo, machine_code, execution_code=execution_code, lot_code=lot_code
        )
        if rec:
            claimed.append(rec)

    labor_code = (meta.get("actual_labor_pool_code") or "").strip()
    if labor_code:
        rec = _mark_labor_in_use(
            repo, labor_code, execution_code=execution_code, lot_code=lot_code
        )
        if rec:
            claimed.append(rec)

    for tool_code in meta.get("actual_tool_codes") or []:
        code = str(tool_code).strip()
        if not code:
            continue
        rec = _mark_tool_in_use(
            repo, code, execution_code=execution_code, lot_code=lot_code
        )
        if rec:
            claimed.append(rec)

    if claimed:
        row.metadata_ = {**meta, "resources_claimed": claimed}
        repo.db.flush()


def release_execution_resources(
    db: Session, tenant: TenantContext, row: OperationExecution
) -> None:
    """Free resources tied to a completed (or released) operation."""
    repo = _repo(db, tenant)
    meta = _meta(row)
    claimed = meta.get("resources_claimed") or []
    if not claimed:
        machine_code = (meta.get("actual_machine_code") or meta.get("assigned_machine_code") or "").strip()
        labor_code = (meta.get("actual_labor_pool_code") or "").strip()
        if machine_code:
            claimed.append({"kind": "machine", "code": machine_code})
        if labor_code:
            claimed.append({"kind": "labor", "code": labor_code})
        for tool_code in meta.get("actual_tool_codes") or []:
            code = str(tool_code).strip()
            if code:
                claimed.append({"kind": "tool", "code": code})

    for record in claimed:
        kind = (record.get("kind") or "").lower()
        if kind == "machine":
            _release_machine(repo, record)
        elif kind == "labor":
            _release_labor(repo, record)
        elif kind == "tool":
            _release_tool(repo, record)

    meta = {
        **meta,
        "resources_released": True,
        "resources_claimed": [],
    }
    meta.pop("planned_start_time", None)
    meta.pop("planned_end_time", None)
    row.metadata_ = meta
    repo.db.flush()
