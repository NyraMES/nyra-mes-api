"""Feasibility checks for nyra_mes_core."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError, WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrder,
    CustomerOrderLine,
    Equipment,
    FeasibilityCheck,
    OperationExecution,
    OperationResourceRequirement,
    ProductionLot,
    ProductionOrder,
    Resource,
)
from app.schemas.feasibility import FeasibilityCheckResult, FeasibilityResponse
from app.schemas.mes_core.schemas import FeasibilityGateOut
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.ids import resolve_business_code
from app.services.mes_core.routing_helpers import (
    AVAILABLE_STATUSES,
    is_resource_available,
    load_lot_routing,
    resolve_operation_machine,
)

_BLOCKED = "BLOCKED"
_OK = "OK"
_WARNING = "WARNING"
_READY_STATUSES = frozenset({"OK", "READY", "PASSED"})
_SCHEDULE_META_FLAG = "is_production_schedule"
_DEFAULT_SLOT_MINUTES = 60.0
# Lots past shop-floor routing should not hold kiln schedule slots in feasibility.
_ROUTING_DONE_LOT_STATUSES = frozenset(
    {
        "QC_PENDING",
        "STOCKED",
        "COMPLETED",
        "DISPATCHED",
        "CLOSED",
        "CANCELLED",
    }
)


def is_ready_for_scheduling(db: Session, tenant: TenantContext, lot_code: str) -> bool:
    gate = get_feasibility_for_lot(db, tenant, lot_code)
    status = (gate.overall_status or "").upper()
    if status in _READY_STATUSES:
        return True
    # Latest persisted row may be OK while UI reconciled to READY — treat OK as schedulable.
    return status == _OK


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _gate_from_row(lot_code: str, row: FeasibilityCheck) -> FeasibilityGateOut:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    overall = (row.overall_status or "PENDING").upper()
    blocked = meta.get("blocked_reason")
    if not blocked and overall == _BLOCKED:
        parts = []
        for key in ("material", "machine", "tool", "workforce", "routing", "schedule_capacity"):
            status = meta.get(f"{key}_status")
            if status and str(status).upper() == _BLOCKED:
                parts.append(f"{key} blocked")
        blocked = "; ".join(parts) if parts else "Feasibility check did not pass"
    return FeasibilityGateOut(
        lot_id=lot_code,
        overall_status=overall,
        material_status=meta.get("material_status"),
        machine_status=meta.get("machine_status"),
        tool_status=meta.get("tool_status"),
        workforce_status=meta.get("workforce_status"),
        blocked_reason=blocked,
        checked_at=row.checked_at,
    )


def get_feasibility_for_lot(
    db: Session, tenant: TenantContext, lot_code: str
) -> FeasibilityGateOut:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    row = (
        repo.query(FeasibilityCheck)
        .filter(FeasibilityCheck.production_lot_id == lot.production_lot_id)
        .order_by(
            FeasibilityCheck.checked_at.desc().nullslast(),
            FeasibilityCheck.created_at.desc(),
        )
        .first()
    )
    if not row:
        return FeasibilityGateOut(
            lot_id=lot_code,
            overall_status=_BLOCKED,
            blocked_reason="No feasibility check found for this lot. Run feasibility first.",
        )
    return _gate_from_row(lot_code, row)


def _is_schedule_row(row: OperationExecution) -> bool:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return bool(meta.get(_SCHEDULE_META_FLAG) or meta.get("schedule_code"))


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _existing_schedule_intervals(
    repo: TenantRepository,
    *,
    exclude_lot_id=None,
) -> dict[str, list[tuple[datetime, datetime, str]]]:
    """Map machine_code -> list of (start, end, lot_code) for timed schedules."""
    by_machine: dict[str, list[tuple[datetime, datetime, str]]] = {}
    rows = repo.query(OperationExecution).all()
    for row in rows:
        if not _is_schedule_row(row):
            continue
        if exclude_lot_id and row.production_lot_id == exclude_lot_id:
            continue
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if meta.get("resources_released"):
            continue
        if (row.status or "").upper() == "COMPLETED":
            continue
        lot = (
            repo.query(ProductionLot)
            .filter(ProductionLot.production_lot_id == row.production_lot_id)
            .first()
        )
        if lot and (lot.status or "").upper() in _ROUTING_DONE_LOT_STATUSES:
            continue
        machine_code = (meta.get("assigned_machine_code") or "").strip()
        if not machine_code:
            continue
        start = _parse_dt(meta.get("planned_start_time"))
        end = _parse_dt(meta.get("planned_end_time"))
        if not start or not end or end <= start:
            continue
        lot_code = lot.lot_code if lot else str(row.production_lot_id)
        by_machine.setdefault(machine_code, []).append((start, end, lot_code))
    return by_machine


def _intervals_overlap(
    start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime
) -> bool:
    return start_a < end_b and start_b < end_a


def assert_machine_available_for_schedule(
    *,
    equipment: Optional[Equipment],
    resource: Optional[Resource],
    machine_code: str,
) -> None:
    """Raise WorkflowError when assigned machine/resource is not schedulable."""
    if equipment and not is_resource_available(equipment.status):
        raise WorkflowError(
            f"Machine '{machine_code}' is not available (status: {equipment.status})",
            details={"machine_code": machine_code, "status": equipment.status},
        )
    if resource and not equipment and not is_resource_available(resource.status):
        raise WorkflowError(
            f"Resource '{machine_code}' is not available (status: {resource.status})",
            details={"machine_code": machine_code, "status": resource.status},
        )


def assert_no_schedule_conflict(
    repo: TenantRepository,
    *,
    machine_code: str,
    planned_start: datetime,
    planned_end: datetime,
    exclude_lot_id=None,
) -> None:
    """Raise WorkflowError when the machine slot overlaps an existing schedule."""
    if planned_end <= planned_start:
        raise ValidationError("planned_end_time must be after planned_start_time")

    existing = _existing_schedule_intervals(repo, exclude_lot_id=exclude_lot_id)
    for ex_start, ex_end, other_lot in existing.get(machine_code, []):
        if _intervals_overlap(planned_start, planned_end, ex_start, ex_end):
            raise WorkflowError(
                f"Machine '{machine_code}' is already scheduled for lot {other_lot} "
                f"from {ex_start.isoformat()} to {ex_end.isoformat()}",
                details={
                    "machine_code": machine_code,
                    "conflict_lot": other_lot,
                    "conflict_start": ex_start.isoformat(),
                    "conflict_end": ex_end.isoformat(),
                },
            )


def _labor_capacity(resource: Resource) -> float:
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    for key in ("operators", "headcount", "available_count", "capacity"):
        if meta.get(key) is not None:
            try:
                return max(float(meta[key]), 0.0)
            except (TypeError, ValueError):
                continue
    return 1.0 if is_resource_available(resource.status) else 0.0


def _run_workforce_checks(
    repo: TenantRepository, operations: list
) -> FeasibilityCheckResult:
    labor_requirements: list[tuple[Any, OperationResourceRequirement]] = []
    for op in operations:
        reqs = (
            repo.query(OperationResourceRequirement)
            .filter(
                OperationResourceRequirement.routing_operation_id
                == op.routing_operation_id,
                OperationResourceRequirement.requirement_type == "LABOR",
            )
            .all()
        )
        for req in reqs:
            labor_requirements.append((op, req))

    labor_pool = (
        repo.query(Resource).filter(Resource.resource_type == "LABOR").all()
    )
    available_pool = [
        row for row in labor_pool if is_resource_available(row.status)
    ]

    if not labor_requirements:
        if not labor_pool:
            return FeasibilityCheckResult(
                resource_type="workforce",
                status=_OK,
                detail="No LABOR requirements on routing; no labor pool registered (assumed available)",
            )
        if not available_pool:
            return FeasibilityCheckResult(
                resource_type="workforce",
                status=_BLOCKED,
                detail=(
                    f"{len(labor_pool)} labor pool(s) registered but none are "
                    "ACTIVE/AVAILABLE/IDLE/READY"
                ),
            )
        return FeasibilityCheckResult(
            resource_type="workforce",
            status=_OK,
            detail=(
                f"{len(available_pool)} labor pool(s) available "
                "(routing has no per-operation LABOR requirements)"
            ),
        )

    issues: List[str] = []
    covered_ops = 0
    for op, req in labor_requirements:
        resource = (
            repo.query(Resource)
            .filter(Resource.resource_id == req.resource_id)
            .first()
        )
        required_qty = float(req.quantity or 1)
        op_label = op.operation_code or op.operation_name

        if not resource:
            issues.append(f"{op_label}: labor resource not found for requirement")
            continue

        if resource.resource_type != "LABOR":
            issues.append(
                f"{op_label}: requirement points to {resource.resource_code} "
                f"({resource.resource_type}), expected LABOR"
            )
            continue

        if not is_resource_available(resource.status):
            issues.append(
                f"{op_label}: labor pool '{resource.resource_code}' is "
                f"{resource.status or 'UNAVAILABLE'}"
            )
            continue

        available_qty = _labor_capacity(resource)
        if available_qty < required_qty:
            issues.append(
                f"{op_label}: needs {required_qty:g} operator(s) from "
                f"'{resource.resource_code}', pool capacity {available_qty:g}"
            )
            continue

        covered_ops += 1

    if issues:
        return FeasibilityCheckResult(
            resource_type="workforce",
            status=_BLOCKED,
            detail="; ".join(issues),
        )

    return FeasibilityCheckResult(
        resource_type="workforce",
        status=_OK,
        detail=(
            f"Workforce OK — {covered_ops} operation(s) covered by available "
            "LABOR pools"
        ),
    )


def _run_tool_checks(repo: TenantRepository, operations: list) -> FeasibilityCheckResult:
    tool_requirements: list[tuple[Any, OperationResourceRequirement]] = []
    for op in operations:
        reqs = (
            repo.query(OperationResourceRequirement)
            .filter(
                OperationResourceRequirement.routing_operation_id
                == op.routing_operation_id,
                OperationResourceRequirement.requirement_type.in_(("TOOL", "SECONDARY")),
            )
            .all()
        )
        for req in reqs:
            tool_requirements.append((op, req))

    if not tool_requirements:
        tool_pool = repo.query(Resource).filter(Resource.resource_type == "TOOL").all()
        if not tool_pool:
            return FeasibilityCheckResult(
                resource_type="tool",
                status=_OK,
                detail="No tool requirements on routing; tooling assumed available",
            )
        available = [row for row in tool_pool if is_resource_available(row.status)]
        if not available:
            return FeasibilityCheckResult(
                resource_type="tool",
                status=_BLOCKED,
                detail="Tool inventory registered but no tools are available",
            )
        return FeasibilityCheckResult(
            resource_type="tool",
            status=_OK,
            detail=f"{len(available)} tool resource(s) available",
        )

    issues: List[str] = []
    for op, req in tool_requirements:
        resource = (
            repo.query(Resource)
            .filter(Resource.resource_id == req.resource_id)
            .first()
        )
        op_label = op.operation_code or op.operation_name
        if not resource:
            issues.append(f"{op_label}: tool resource not found")
            continue
        if not is_resource_available(resource.status):
            issues.append(
                f"{op_label}: tool '{resource.resource_code}' is "
                f"{resource.status or 'UNAVAILABLE'}"
            )

    if issues:
        return FeasibilityCheckResult(
            resource_type="tool",
            status=_BLOCKED,
            detail="; ".join(issues),
        )
    return FeasibilityCheckResult(
        resource_type="tool",
        status=_OK,
        detail=f"Tooling OK — {len(tool_requirements)} requirement(s) satisfied",
    )


def _run_material_checks(
    repo: TenantRepository, lot: ProductionLot
) -> FeasibilityCheckResult:
    """Validate feedstock / order readiness for the lot's production order."""
    po = repo.get_by_pk(
        ProductionOrder,
        ProductionOrder.production_order_id,
        lot.production_order_id,
    )
    line = repo.get_by_pk(
        CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
    )
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, line.order_id
    )
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    qc = meta.get("raw_material_qc") if isinstance(meta.get("raw_material_qc"), dict) else {}
    qc_status = str(qc.get("qc_status") or "PENDING").upper()

    if meta.get("flow") == "RAW_MATERIAL_INWARD" or qc:
        if qc_status in ("PASS", "QC_PASSED"):
            return FeasibilityCheckResult(
                resource_type="material",
                status=_OK,
                detail=(
                    f"Raw material QC passed for order {order.order_code} "
                    f"(lot {lot.lot_code}, {lot.lot_quantity} KG)"
                ),
            )
        if qc_status in ("FAIL", "QC_FAILED", "HOLD"):
            return FeasibilityCheckResult(
                resource_type="material",
                status=_BLOCKED,
                detail=(
                    f"Raw material QC is {qc_status} on order {order.order_code} — "
                    "resolve on Raw Material QC before feasibility"
                ),
            )
        return FeasibilityCheckResult(
            resource_type="material",
            status=_BLOCKED,
            detail=(
                f"Raw material QC pending for order {order.order_code} — "
                "complete Raw Material QC before feasibility"
            ),
        )

    return FeasibilityCheckResult(
        resource_type="material",
        status=_OK,
        detail=f"Production order {po.production_order_code} linked to lot {lot.lot_code}",
    )


def _run_kiln_resource_check(repo: TenantRepository) -> Optional[FeasibilityCheckResult]:
    """Activated Carbon: ensure at least one activation kiln resource exists and is available."""
    kilns = (
        repo.query(Resource)
        .filter(Resource.resource_code.like("RES-KILN%"))
        .order_by(Resource.resource_code)
        .all()
    )
    if not kilns:
        return None
    available = [k for k in kilns if is_resource_available(k.status)]
    if not available:
        codes = ", ".join(k.resource_code for k in kilns)
        return FeasibilityCheckResult(
            resource_type="machine",
            status=_BLOCKED,
            detail=f"Activation kiln(s) unavailable: {codes}",
        )
    return FeasibilityCheckResult(
        resource_type="machine",
        status=_OK,
        detail=f"Kiln available: {available[0].resource_code} ({available[0].resource_name or 'Activation'})",
    )


def _run_tenant_checks(repo: TenantRepository) -> List[FeasibilityCheckResult]:
    checks: List[FeasibilityCheckResult] = []

    equipment_rows = repo.query(Equipment).all()
    available_equipment = sum(
        1 for row in equipment_rows if is_resource_available(row.status)
    )
    machine_resources = (
        repo.query(Resource)
        .filter(Resource.resource_type.in_(("MACHINE", "WORKCELL", "LINE")))
        .all()
    )
    available_resources = sum(
        1 for row in machine_resources if is_resource_available(row.status)
    )

    if available_equipment == 0 and available_resources == 0:
        if equipment_rows or machine_resources:
            checks.append(
                FeasibilityCheckResult(
                    resource_type="machine",
                    status=_BLOCKED,
                    detail=(
                        "No machines in Available/Active/Idle state — "
                        f"{len(equipment_rows)} equipment and {len(machine_resources)} "
                        "machine resources are registered but none are available"
                    ),
                )
            )
        else:
            checks.append(
                FeasibilityCheckResult(
                    resource_type="machine",
                    status=_BLOCKED,
                    detail="No equipment or machine resources registered for this tenant",
                )
            )
    else:
        detail = None
        if available_equipment == 0 and available_resources > 0:
            detail = (
                f"{available_resources} machine resource(s) available "
                "(no equipment marked available)"
            )
        elif available_resources == 0 and available_equipment > 0:
            detail = f"{available_equipment} equipment unit(s) available"
        checks.append(
            FeasibilityCheckResult(
                resource_type="machine",
                status=_OK,
                detail=detail,
            )
        )

    return checks


def _run_lot_checks(
    repo: TenantRepository, lot: ProductionLot
) -> List[FeasibilityCheckResult]:
    checks: List[FeasibilityCheckResult] = []
    checks.append(_run_material_checks(repo, lot))
    kiln_check = _run_kiln_resource_check(repo)
    if kiln_check:
        checks.append(kiln_check)

    product, routing, operations, lot_qty = load_lot_routing(repo, lot)

    if not routing or not operations:
        product_code = product.product_code if product else "unknown"
        checks.append(
            FeasibilityCheckResult(
                resource_type="routing",
                status=_BLOCKED,
                detail=(
                    f"No active routing with operations for product '{product_code}'. "
                    "Create routing in Routing Master before scheduling."
                ),
            )
        )
        return checks

    checks.append(
        FeasibilityCheckResult(
            resource_type="routing",
            status=_OK,
            detail=(
                f"Routing {routing.routing_code} v{routing.routing_version} — "
                f"{len(operations)} operation(s)"
            ),
        )
    )

    assignment_issues: List[str] = []
    for op in operations:
        resolved = resolve_operation_machine(repo, op)
        machine_code = resolved.get("machine_code")
        equipment = resolved.get("equipment")
        resource = resolved.get("resource")
        op_label = op.operation_code or op.operation_name

        if not machine_code:
            assignment_issues.append(f"{op_label}: no machine or work-center can be assigned")
            continue

        if equipment and not is_resource_available(equipment.status):
            assignment_issues.append(
                f"{op_label}: equipment '{machine_code}' is {equipment.status or 'UNAVAILABLE'}"
            )
        elif resource and not equipment and not is_resource_available(resource.status):
            assignment_issues.append(
                f"{op_label}: resource '{machine_code}' is {resource.status or 'UNAVAILABLE'}"
            )

    if assignment_issues:
        checks.append(
            FeasibilityCheckResult(
                resource_type="machine",
                status=_BLOCKED,
                detail="; ".join(assignment_issues),
            )
        )
    else:
        checks.append(
            FeasibilityCheckResult(
                resource_type="machine_assignment",
                status=_OK,
                detail=f"All {len(operations)} routing step(s) have an available machine/resource",
            )
        )

    checks.append(_run_tool_checks(repo, operations))
    checks.append(_run_workforce_checks(repo, operations))

    conflicts = _simulate_routing_slot_conflicts(repo, lot, operations, lot_qty)
    if conflicts:
        checks.append(
            FeasibilityCheckResult(
                resource_type="schedule_capacity",
                status=_BLOCKED,
                detail=conflicts[0],
            )
        )
    else:
        timed_count = sum(
            len(v) for v in _existing_schedule_intervals(repo, exclude_lot_id=lot.production_lot_id).values()
        )
        detail = "No other lot is using the kiln — you can proceed."
        if timed_count == 0:
            detail = "Kiln schedule is clear — no other lots booked yet."
        checks.append(
            FeasibilityCheckResult(
                resource_type="schedule_capacity",
                status=_OK,
                detail=detail,
            )
        )

    return checks


def _simulate_routing_slot_conflicts(
    repo: TenantRepository,
    lot: ProductionLot,
    operations: list,
    lot_qty: float,
) -> List[str]:
    """Estimate sequential slots per machine and detect overlaps with existing schedules."""
    existing = _existing_schedule_intervals(repo, exclude_lot_id=lot.production_lot_id)
    if not any(existing.values()):
        return []

    now = datetime.now(timezone.utc)
    machine_cursors: dict[str, datetime] = {}
    blocked_machines: dict[str, str] = {}

    for op in operations:
        resolved = resolve_operation_machine(repo, op)
        machine_code = resolved.get("machine_code")
        if not machine_code or machine_code in blocked_machines:
            continue

        cycle = float(op.standard_cycle_min) if op.standard_cycle_min is not None else 0.0
        duration_min = cycle * lot_qty if cycle > 0 else _DEFAULT_SLOT_MINUTES
        start = machine_cursors.get(machine_code, now)
        end = start + timedelta(minutes=duration_min)

        for ex_start, ex_end, other_lot in existing.get(machine_code, []):
            if _intervals_overlap(start, end, ex_start, ex_end):
                blocked_machines[machine_code] = other_lot
                break

        machine_cursors[machine_code] = end

    conflicts: List[str] = []
    for machine_code, other_lot in blocked_machines.items():
        resource_label = "the activation kiln" if "KILN" in machine_code.upper() else machine_code
        conflicts.append(
            f"Lot {other_lot} is using {resource_label}. "
            f"Please wait for that process to complete."
        )

    # One user-facing sentence — first blocking lot only.
    return conflicts[:1]


def _run_checks(
    repo: TenantRepository, lot: ProductionLot
) -> tuple[List[FeasibilityCheckResult], dict[str, str]]:
    checks = _run_tenant_checks(repo) + _run_lot_checks(repo, lot)

    summary: dict[str, str] = {
        "material": _OK,
        "tool": _OK,
        "workforce": _OK,
        "machine": _OK,
        "routing": _OK,
        "schedule_capacity": _OK,
    }
    for check in checks:
        if check.resource_type in summary and check.status == _BLOCKED:
            summary[check.resource_type] = _BLOCKED
        if check.resource_type == "machine_assignment" and check.status == _BLOCKED:
            summary["machine"] = _BLOCKED

    return checks, summary


def run_feasibility_check(
    db: Session, tenant: TenantContext, lot_code: str
) -> FeasibilityResponse:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    checks, summary = _run_checks(repo, lot)

    stored_status = _BLOCKED if any(c.status == _BLOCKED for c in checks) else _OK
    blocked_parts: List[str] = []
    seen_types: set[str] = set()
    for check in checks:
        if check.status != _BLOCKED or not check.detail:
            continue
        rtype = check.resource_type or ""
        if rtype in seen_types:
            continue
        seen_types.add(rtype)
        detail = check.detail.split(";")[0].strip()
        blocked_parts.append(detail)
    blocked_reason = " ".join(blocked_parts) if blocked_parts else None
    checked_at = datetime.now(timezone.utc)

    metadata = {
        **summary,
        "material_status": summary.get("material"),
        "machine_status": summary.get("machine"),
        "tool_status": summary.get("tool"),
        "workforce_status": summary.get("workforce"),
        "routing_status": summary.get("routing"),
        "schedule_capacity_status": summary.get("schedule_capacity"),
        "blocked_reason": blocked_reason,
        "checks": [
            {"resource_type": c.resource_type, "status": c.status, "detail": c.detail}
            for c in checks
        ],
    }

    code = resolve_business_code(db, provided=None, entity="feasibility_check")
    row = repo.add(
        FeasibilityCheck(
            check_code=code,
            production_lot_id=lot.production_lot_id,
            overall_status=stored_status,
            checked_at=checked_at,
            metadata_=metadata,
        )
    )
    repo.commit_refresh(row)

    return FeasibilityResponse(
        lot_id=lot_code,
        overall_status=stored_status,
        material_status=summary.get("material"),
        machine_status=summary.get("machine"),
        tool_status=summary.get("tool"),
        workforce_status=summary.get("workforce"),
        blocked_reason=blocked_reason,
        checked_at=checked_at,
        checks=checks,
    )
