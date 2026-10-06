"""Claim and release plant resources (kiln, labor pool, tools) during shop-floor execution."""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.tenant_context import TenantContext
from app.core.exceptions import ValidationError, WorkflowError
from app.models.mes_core import Equipment, OperationExecution, ProductionLot, Resource
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.routing_helpers import is_resource_available

_IN_USE_STATUS = "IN_USE"
_AVAILABLE_STATUS = "AVAILABLE"
_KILN_RELEASE_PROCESS_STEPS = frozenset({"ACTIVATION", "PYROLYSIS"})
_RUNNING_EXEC_STATUSES = frozenset(
    {"IN_PROGRESS", "STARTED", "RUNNING", "PAUSED", "ACTIVE", "IN_KILN"}
)


def _active_owner(obj: Equipment | Resource | None) -> tuple[str, str]:
    if not obj:
        return "", ""
    meta = obj.metadata_ if isinstance(obj.metadata_, dict) else {}
    lot = (meta.get("active_lot_code") or "").strip()
    execution = (meta.get("active_execution_code") or "").strip()
    return lot, execution


def _machine_available_for_lot(
    equipment: Optional[Equipment],
    resource: Optional[Resource],
    *,
    lot_code: str,
) -> tuple[bool, str]:
    for obj in (equipment, resource):
        if not obj:
            continue
        if is_resource_available(obj.status):
            continue
        owner_lot, _ = _active_owner(obj)
        if owner_lot and owner_lot == lot_code:
            continue
        return False, owner_lot or "another lot"
    return True, ""


def _labor_available_for_lot(resource: Resource, *, lot_code: str) -> tuple[bool, str]:
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    in_use = int(meta.get("in_use_count") or 0)
    capacity = _labor_headcount(resource)
    owner_lot, _ = _active_owner(resource)
    if capacity > 0 and in_use >= capacity:
        if owner_lot and owner_lot != lot_code:
            return False, owner_lot
    elif not is_resource_available(resource.status):
        if owner_lot and owner_lot != lot_code:
            return False, owner_lot
    return True, ""


def _tool_available_for_lot(resource: Resource, *, lot_code: str) -> tuple[bool, str]:
    if is_resource_available(resource.status):
        return True, ""
    owner_lot, _ = _active_owner(resource)
    if owner_lot and owner_lot == lot_code:
        return True, ""
    return False, owner_lot or "another lot"


def assert_resources_available(
    db: Session,
    tenant: TenantContext,
    *,
    lot_code: str,
    machine_code: str = "",
    labor_code: str = "",
    tool_codes: Optional[List[str]] = None,
) -> None:
    """Raise when assigned plant resources are already in use by another lot."""
    repo = _repo(db, tenant)
    machine = (machine_code or "").strip()
    if machine:
        equipment, resource = _resource_for_machine(repo, machine)
        if not equipment and not resource:
            raise ValidationError(f"Machine '{machine}' was not found in plant resources")
        ok, owner = _machine_available_for_lot(equipment, resource, lot_code=lot_code)
        if not ok:
            raise WorkflowError(
                f"Machine '{machine}' is not available"
                + (f" (in use by lot {owner})" if owner else "")
            )

    labor = (labor_code or "").strip()
    if labor:
        resource = _find_resource(repo, labor)
        if not resource:
            raise ValidationError(f"Labor pool '{labor}' was not found")
        if (resource.resource_type or "").upper() != "LABOR":
            raise ValidationError(f"Resource '{labor}' is not a labor pool")
        ok, owner = _labor_available_for_lot(resource, lot_code=lot_code)
        if not ok:
            raise WorkflowError(
                f"Labor pool '{labor}' is not available"
                + (f" (in use by lot {owner})" if owner else "")
            )

    for tool_code in tool_codes or []:
        code = str(tool_code).strip()
        if not code:
            continue
        resource = _find_resource(repo, code)
        if not resource:
            raise ValidationError(f"Tool '{code}' was not found")
        ok, owner = _tool_available_for_lot(resource, lot_code=lot_code)
        if not ok:
            raise WorkflowError(
                f"Tool '{code}' is not available"
                + (f" (in use by lot {owner})" if owner else "")
            )


def claim_kiln_for_lot(
    db: Session,
    tenant: TenantContext,
    kiln_code: str,
    *,
    lot_code: str,
    share: bool = False,
) -> None:
    """Reserve a kiln when a lot is charged. share=True allows more bags/lots in the same kiln."""
    code = (kiln_code or "").strip()
    if not code:
        return
    repo = _repo(db, tenant)
    if share:
        equipment, resource = _resource_for_machine(repo, code)
        if not equipment and not resource:
            raise ValidationError(f"Kiln resource '{code}' was not found")
    else:
        assert_resources_available(db, tenant, lot_code=lot_code, machine_code=code)
    rec = _mark_machine_in_use(
        repo, code, execution_code=f"kiln:{lot_code}", lot_code=lot_code
    )
    if not rec:
        raise ValidationError(f"Kiln resource '{code}' was not found")


def release_kiln_for_lot(
    db: Session,
    tenant: TenantContext,
    *,
    lot_code: str,
    kiln_code: str,
) -> None:
    """Free a kiln after activation / pyrolysis completes."""
    code = (kiln_code or "").strip()
    if not code:
        return
    repo = _repo(db, tenant)
    _release_machine(repo, {"kind": "machine", "code": code})


def release_lot_kiln_if_claimed(
    db: Session, tenant: TenantContext, lot: ProductionLot
) -> None:
    """Release kiln tied to lot metadata after the firing cycle ends."""
    meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    kiln_code = (meta.get("kiln_resource_code") or "").strip()
    if not kiln_code:
        return
    if not meta.get("kiln_resource_claimed") and meta.get("kiln_live_status") != "IN_KILN":
        return
    release_kiln_for_lot(db, tenant, lot_code=lot.lot_code, kiln_code=kiln_code)
    lot.metadata_ = {
        **meta,
        "kiln_live_status": "AVAILABLE",
        "kiln_resource_claimed": False,
    }
    repo = _repo(db, tenant)
    repo.db.flush()


def kiln_release_step(process_step: Optional[str]) -> bool:
    return (process_step or "").upper() in _KILN_RELEASE_PROCESS_STEPS


def lot_has_running_execution(repo: TenantRepository, lot: ProductionLot) -> bool:
    """True only when a shop-floor execution is actually in progress."""
    rows = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot.production_lot_id)
        .all()
    )
    return any((row.status or "").upper() in _RUNNING_EXEC_STATUSES for row in rows)


def release_stale_kiln_claims(db: Session, tenant: TenantContext) -> int:
    """Free kilns left IN_USE after kiln feed when no lot is actually running."""
    repo = _repo(db, tenant)
    released = 0
    kilns = (
        repo.query(Resource)
        .filter(Resource.resource_code.like("RES-KILN%"))
        .all()
    )
    for kiln in kilns:
        meta = kiln.metadata_ if isinstance(kiln.metadata_, dict) else {}
        lot_code = (meta.get("active_lot_code") or "").strip()
        busy = (kiln.status or "").upper() == _IN_USE_STATUS or bool(lot_code)
        if not busy:
            continue
        lot = None
        if lot_code:
            lot = (
                repo.query(ProductionLot)
                .filter(ProductionLot.lot_code == lot_code)
                .first()
            )
        if lot and lot_has_running_execution(repo, lot):
            continue
        release_kiln_for_lot(db, tenant, lot_code=lot_code or "", kiln_code=kiln.resource_code)
        if lot:
            lot_meta = dict(lot.metadata_ if isinstance(lot.metadata_, dict) else {})
            lot.metadata_ = {
                **lot_meta,
                "kiln_live_status": "AVAILABLE",
                "kiln_resource_claimed": False,
            }
            flag_modified(lot, "metadata_")
        released += 1
    if released:
        repo.db.flush()
    return released


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
        emeta = dict(equipment.metadata_ if isinstance(equipment.metadata_, dict) else {})
        emeta.pop("active_execution_code", None)
        emeta.pop("active_lot_code", None)
        equipment.metadata_ = emeta
        equipment.status = _AVAILABLE_STATUS
        flag_modified(equipment, "metadata_")
    if resource:
        rmeta = dict(resource.metadata_ if isinstance(resource.metadata_, dict) else {})
        rmeta.pop("active_execution_code", None)
        rmeta.pop("active_lot_code", None)
        resource.metadata_ = rmeta
        if is_resource_available(resource.status) or resource.status == _IN_USE_STATUS:
            resource.status = _AVAILABLE_STATUS
        flag_modified(resource, "metadata_")


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
    machine_code = (meta.get("actual_machine_code") or meta.get("assigned_machine_code") or "").strip()
    labor_code = (meta.get("actual_labor_pool_code") or "").strip()
    tool_codes = [
        str(tool_code).strip()
        for tool_code in (meta.get("actual_tool_codes") or [])
        if str(tool_code).strip()
    ]

    assert_resources_available(
        db,
        tenant,
        lot_code=lot_code,
        machine_code=machine_code,
        labor_code=labor_code,
        tool_codes=tool_codes,
    )

    claimed: List[dict[str, Any]] = []
    if machine_code:
        rec = _mark_machine_in_use(
            repo, machine_code, execution_code=execution_code, lot_code=lot_code
        )
        if rec:
            claimed.append(rec)

    if labor_code:
        rec = _mark_labor_in_use(
            repo, labor_code, execution_code=execution_code, lot_code=lot_code
        )
        if rec:
            claimed.append(rec)

    for code in tool_codes:
        rec = _mark_tool_in_use(
            repo, code, execution_code=execution_code, lot_code=lot_code
        )
        if rec:
            claimed.append(rec)

    if claimed:
        row.metadata_ = {**meta, "resources_claimed": claimed}
        repo.db.flush()


def release_execution_resources(
    db: Session,
    tenant: TenantContext,
    row: OperationExecution,
    *,
    for_hold: bool = False,
) -> None:
    """Free resources tied to a completed (or released) operation."""
    repo = _repo(db, tenant)
    meta = _meta(row)
    claimed = list(meta.get("resources_claimed") or [])
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

    meta = {**meta, "resources_claimed": []}
    if for_hold:
        meta["resources_suspended"] = claimed
    else:
        meta["resources_released"] = True
        meta.pop("resources_suspended", None)
        meta.pop("planned_start_time", None)
        meta.pop("planned_end_time", None)
    row.metadata_ = meta
    repo.db.flush()


def restore_execution_resources(
    db: Session, tenant: TenantContext, row: OperationExecution, *, lot_code: str
) -> None:
    """Re-claim resources after an operation resumes from hold."""
    meta = _meta(row)
    if meta.get("resources_claimed"):
        return
    claim_execution_resources(db, tenant, row, lot_code=lot_code)
    meta = _meta(row)
    meta.pop("resources_suspended", None)
    row.metadata_ = meta
    repo = _repo(db, tenant)
    repo.db.flush()


def release_all_tenant_plant_resources(
    db: Session, tenant: TenantContext
) -> dict[str, int]:
    """Force-release every tool, labor pool, machine, and kiln for a tenant."""
    from datetime import datetime, timezone

    repo = _repo(db, tenant)
    now = datetime.now(timezone.utc).isoformat()
    counts = {"equipment": 0, "resources": 0, "lots": 0, "executions": 0}

    for row in repo.query(Equipment).all():
        emeta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        busy = (row.status or "").upper() == _IN_USE_STATUS
        busy = busy or bool(emeta.get("active_lot_code") or emeta.get("active_execution_code"))
        if not busy:
            continue
        emeta.pop("active_execution_code", None)
        emeta.pop("active_lot_code", None)
        row.metadata_ = emeta
        row.status = _AVAILABLE_STATUS
        counts["equipment"] += 1

    for row in repo.query(Resource).all():
        rmeta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        changed = False
        if (row.status or "").upper() == _IN_USE_STATUS:
            row.status = _AVAILABLE_STATUS
            changed = True
        if rmeta.get("active_lot_code") or rmeta.get("active_execution_code"):
            rmeta.pop("active_execution_code", None)
            rmeta.pop("active_lot_code", None)
            changed = True
        if int(rmeta.get("in_use_count") or 0) > 0:
            rmeta["in_use_count"] = 0
            changed = True
        if changed:
            row.metadata_ = rmeta
            counts["resources"] += 1

    for lot in repo.query(ProductionLot).all():
        meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        if not meta.get("kiln_resource_claimed") and meta.get("kiln_live_status") != "IN_KILN":
            continue
        lot.metadata_ = {
            **meta,
            "kiln_live_status": "AVAILABLE",
            "kiln_resource_claimed": False,
        }
        counts["lots"] += 1

    for row in repo.query(OperationExecution).all():
        meta = _meta(row)
        needs_release = bool(meta.get("resources_claimed")) or not meta.get("resources_released")
        if not needs_release:
            continue
        for record in meta.get("resources_claimed") or []:
            kind = (record.get("kind") or "").lower()
            if kind == "machine":
                _release_machine(repo, record)
            elif kind == "labor":
                _release_labor(repo, record)
            elif kind == "tool":
                _release_tool(repo, record)
        cleaned = dict(meta)
        cleaned["resources_released"] = True
        cleaned["resources_released_at"] = now
        cleaned["resources_claimed"] = []
        cleaned.pop("resources_suspended", None)
        cleaned.pop("planned_start_time", None)
        cleaned.pop("planned_end_time", None)
        row.metadata_ = cleaned
        counts["executions"] += 1

    repo.db.commit()
    return counts
