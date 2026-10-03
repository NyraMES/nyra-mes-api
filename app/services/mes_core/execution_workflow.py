"""Shop-floor execution for nyra_mes_core.

Work orders map to ``exec.operation_execution`` rows created during scheduling
(``metadata.is_production_schedule``).  Start / hold / resume / complete update
the same record the scheduling board created.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError, WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    Customer,
    CustomerOrder,
    CustomerOrderLine,
    OperationExecution,
    OperationResourceRequirement,
    ParameterReading,
    Product,
    ProductionLot,
    ProductionOrder,
    Resource,
    RoutingOperation,
    RoutingOperationParameter,
)
from app.schemas.schedule import (
    ParameterReadingInput,
    WorkOrderCompleteRequest,
    WorkOrderHoldRequest,
    WorkOrderOut,
    WorkOrderStartRequest,
)
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.routing_helpers import resolve_operation_machine

_SCHEDULE_META_FLAG = "is_production_schedule"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _meta(row: OperationExecution) -> dict[str, Any]:
    data = row.metadata_ or {}
    return data if isinstance(data, dict) else {}


def _is_schedule_row(row: OperationExecution) -> bool:
    meta = _meta(row)
    return bool(meta.get(_SCHEDULE_META_FLAG) or meta.get("schedule_code"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _db_work_order_status(status: str) -> str:
    s = (status or "").upper()
    if s == "NOT_STARTED":
        return "Released"
    if s == "IN_PROGRESS":
        return "InProgress"
    if s == "COMPLETED":
        return "Completed"
    if s == "HOLD":
        return "OnHold"
    return status or "Released"


def _ui_status(status: str) -> str:
    s = (status or "").upper()
    if s == "NOT_STARTED":
        return "Ready"
    if s == "IN_PROGRESS":
        return "In Progress"
    if s == "COMPLETED":
        return "Completed"
    if s == "HOLD":
        return "On Hold"
    return "Pending"


def _get_execution_by_code(
    db: Session, tenant: TenantContext, execution_code: str
) -> OperationExecution:
    row = _repo(db, tenant).get_by_code(
        OperationExecution, OperationExecution.execution_code, execution_code
    )
    if not _is_schedule_row(row):
        raise NotFoundError(f"Work order '{execution_code}' not found")
    return row


def _execution_to_work_order_out(
    db: Session,
    tenant: TenantContext,
    row: OperationExecution,
    rop: Optional[RoutingOperation] = None,
) -> WorkOrderOut:
    meta = _meta(row)
    repo = _repo(db, tenant)
    if rop is None:
        rop = (
            repo.query(RoutingOperation)
            .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
            .first()
        )
    lot = (
        repo.query(ProductionLot)
        .filter(ProductionLot.production_lot_id == row.production_lot_id)
        .first()
    )
    downtime = meta.get("downtime_minutes")
    return WorkOrderOut(
        work_order_id=row.execution_code,
        schedule_id=meta.get("schedule_code"),
        lot_id=lot.lot_code if lot else None,
        operation_id=rop.operation_code if rop else None,
        work_order_status=_db_work_order_status(row.status),
        released_at=_parse_dt(meta.get("released_at")),
        started_at=row.started_at,
        completed_at=row.completed_at,
        actual_output_quantity=_decimal_or_none(meta.get("actual_output_quantity")),
        scrap_quantity=_decimal_or_none(meta.get("scrap_quantity")),
        rework_quantity=_decimal_or_none(meta.get("rework_quantity")),
        operator_name=meta.get("operator_name"),
        actual_machine_id=meta.get("actual_machine_code") or meta.get("assigned_machine_code"),
        downtime_minutes=_decimal_or_none(downtime),
    )


def _planned_resources_for_op(
    repo: TenantRepository, rop: Optional[RoutingOperation]
) -> dict[str, Any]:
    if not rop:
        return {}
    resolved = resolve_operation_machine(repo, rop)
    reqs = (
        repo.query(OperationResourceRequirement)
        .filter(
            OperationResourceRequirement.routing_operation_id
            == rop.routing_operation_id
        )
        .all()
    )
    tool_codes: list[str] = []
    labor_pool_code: Optional[str] = None
    for req in reqs:
        resource = (
            repo.query(Resource).filter(Resource.resource_id == req.resource_id).first()
        )
        if not resource:
            continue
        req_type = (req.requirement_type or "").upper()
        if req_type in ("TOOL", "SECONDARY"):
            tool_codes.append(resource.resource_code)
        elif req_type == "LABOR" and not labor_pool_code:
            labor_pool_code = resource.resource_code
    return {
        "machine_code": resolved.get("machine_code"),
        "work_center_code": resolved.get("work_center_code"),
        "tool_codes": tool_codes,
        "labor_pool_code": labor_pool_code,
    }


def resolve_start_resource_selection(
    repo: TenantRepository,
    rop: Optional[RoutingOperation],
    payload: Optional[WorkOrderStartRequest],
) -> dict[str, Any]:
    """Resolve machine, labor, and tool codes for a shop-floor start request."""
    planned = _planned_resources_for_op(repo, rop)
    machine_code = (
        (payload.machine_id if payload else None) or ""
    ).strip() or (planned.get("machine_code") or "")
    labor_pool = (
        (payload.labor_pool_code if payload else None) or ""
    ).strip() or (planned.get("labor_pool_code") or "")
    tool_codes: list[str] = []
    if payload and payload.tool_codes:
        tool_codes = [str(c).strip() for c in payload.tool_codes if str(c).strip()]
    elif planned.get("tool_codes"):
        tool_codes = list(planned["tool_codes"])
    return {
        "machine_code": machine_code,
        "labor_pool_code": labor_pool,
        "tool_codes": tool_codes,
    }


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


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _assert_prior_operations_complete(
    db: Session,
    tenant: TenantContext,
    row: OperationExecution,
    rop: RoutingOperation,
) -> None:
    repo = _repo(db, tenant)
    prior_ops = (
        repo.query(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == rop.routing_id,
            RoutingOperation.operation_sequence < rop.operation_sequence,
        )
        .all()
    )
    if not prior_ops:
        return

    lot_executions = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == row.production_lot_id)
        .all()
    )
    by_op = {
        ex.routing_operation_id: ex
        for ex in lot_executions
        if _is_schedule_row(ex)
    }

    for pop in prior_ops:
        prior = by_op.get(pop.routing_operation_id)
        if prior and (prior.status or "").upper() != "COMPLETED":
            raise WorkflowError(
                f"Complete step {pop.operation_sequence} ({pop.operation_name}) "
                "before starting this operation",
                details={
                    "blocking_operation": pop.operation_code,
                    "blocking_work_order": prior.execution_code,
                },
            )


def _can_start(
    row: OperationExecution,
    rop: Optional[RoutingOperation],
    rows: List[Tuple[OperationExecution, Optional[RoutingOperation]]],
) -> bool:
    if (row.status or "").upper() != "NOT_STARTED" or row.started_at:
        return False
    if not rop or rop.operation_sequence is None:
        return True
    for other, other_rop in rows:
        if (
            other_rop
            and other_rop.routing_id == rop.routing_id
            and other_rop.operation_sequence is not None
            and other_rop.operation_sequence < rop.operation_sequence
            and (other.status or "").upper() != "COMPLETED"
        ):
            return False
    return True


def lot_execution_summary(
    db: Session, tenant: TenantContext, lot_code: str, *, sync: bool = False
) -> Dict[str, Any]:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)

    po = repo.get_by_pk(
        ProductionOrder,
        ProductionOrder.production_order_id,
        lot.production_order_id,
    )
    line = repo.get_by_pk(
        CustomerOrderLine,
        CustomerOrderLine.order_line_id,
        po.order_line_id,
    )
    product = repo.get_by_pk(Product, Product.product_id, line.product_id)
    order = repo.get_by_pk(
        CustomerOrder,
        CustomerOrder.customer_order_id,
        line.order_id,
    )
    customer = None
    if order.customer_id is not None:
        customer = repo.get_by_pk(
            Customer,
            Customer.customer_id,
            order.customer_id,
        )

    executions = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot.production_lot_id)
        .all()
    )
    schedule_rows = [ex for ex in executions if _is_schedule_row(ex)]

    if sync:
        for ex in schedule_rows:
            meta = _meta(ex)
            if not meta.get("released_at") and (ex.status or "").upper() == "NOT_STARTED":
                meta = {**meta, "released_at": _utcnow().isoformat()}
                ex.metadata_ = meta
        if schedule_rows:
            repo.db.commit()

    rows: List[Tuple[OperationExecution, Optional[RoutingOperation]]] = []
    for ex in schedule_rows:
        rop = (
            repo.query(RoutingOperation)
            .filter(RoutingOperation.routing_operation_id == ex.routing_operation_id)
            .first()
        )
        rows.append((ex, rop))

    rows.sort(
        key=lambda pair: (
            pair[1].operation_sequence is None if pair[1] else True,
            pair[1].operation_sequence if pair[1] else 999999,
            pair[0].execution_code,
        )
    )

    operations = []
    for ex, rop in rows:
        meta = _meta(ex)
        ui = _ui_status(ex.status)
        planned = _planned_resources_for_op(repo, rop)
        param_defs = (
            _parameter_defs_for_operation(repo, rop.routing_operation_id) if rop else []
        )
        captured = _captured_readings_for_execution(repo, ex.execution_id)
        rop_meta = rop.metadata_ if rop and isinstance(rop.metadata_, dict) else {}
        process_step = (
            rop_meta.get("process_step")
            or rop_meta.get("process_code")
            or rop_meta.get("process_type")
            or meta.get("process_step")
        )
        operations.append(
            {
                "work_order_id": ex.execution_code,
                "lot_operation_id": ex.execution_code,
                "operation_id": rop.operation_code if rop else None,
                "operation_code": rop.operation_code if rop else None,
                "operation_name": (rop.operation_name if rop else None)
                or (rop.operation_code if rop else ex.execution_code),
                "seq": rop.operation_sequence if rop else None,
                "operation_sequence": rop.operation_sequence if rop else None,
                "process_step": process_step,
                "is_mandatory": rop_meta.get("is_mandatory", meta.get("is_mandatory", True)),
                "status": ui,
                "work_order_status": _db_work_order_status(ex.status),
                "schedule_id": meta.get("schedule_code"),
                "assigned_machine_id": meta.get("assigned_machine_code")
                or planned.get("machine_code"),
                "assigned_work_center_id": meta.get("assigned_work_center_code")
                or planned.get("work_center_code"),
                "planned_resources": planned,
                "hold_reason": meta.get("hold_reason"),
                "can_start": _can_start(ex, rop, rows),
                "actual_output_quantity": _decimal_or_none(
                    meta.get("actual_output_quantity")
                ),
                "scrap_quantity": _decimal_or_none(meta.get("scrap_quantity")),
                "rework_quantity": _decimal_or_none(meta.get("rework_quantity")),
                "operator_name": meta.get("operator_name"),
                "actual_machine_id": meta.get("actual_machine_code")
                or meta.get("assigned_machine_code"),
                "actual_labor_pool_code": meta.get("actual_labor_pool_code"),
                "actual_tool_codes": meta.get("actual_tool_codes") or [],
                "downtime_minutes": (
                    float(meta["downtime_minutes"])
                    if meta.get("downtime_minutes") is not None
                    else None
                ),
                "released_at": _parse_dt(meta.get("released_at")),
                "started_at": ex.started_at,
                "completed_at": ex.completed_at,
                "parameters": param_defs,
                "captured_readings": captured,
            }
        )

    total = len(rows)
    completed = sum(1 for ex, _ in rows if (ex.status or "").upper() == "COMPLETED")
    in_progress = sum(1 for ex, _ in rows if (ex.status or "").upper() == "IN_PROGRESS")
    ready_count = sum(1 for op in operations if op["status"] == "Ready")
    on_hold_count = sum(1 for op in operations if op["status"] == "On Hold")

    return {
        "lot_id": lot_code,
        "lot_status": lot.status,
        "lot_quantity": float(lot.lot_quantity),
        "production_order_id": po.production_order_code,
        "customer_order_id": order.order_code,
        "customer_id": customer.customer_code if customer else None,
        "part_id": product.product_code,
        "part_name": product.product_name,
        "operations_total": total,
        "operations_completed": completed,
        "operations_in_progress": in_progress,
        "operations_ready": ready_count,
        "operations_on_hold": on_hold_count,
        "schedules_count": len(schedule_rows),
        "execution_ready": total > 0
        and (ready_count > 0 or in_progress > 0 or on_hold_count > 0),
        "sync": {"sync_skipped": not sync, "schedules_found": len(schedule_rows)},
        "operations": operations,
    }


def start_execution(
    db: Session,
    tenant: TenantContext,
    execution_code: str,
    payload: Optional[WorkOrderStartRequest] = None,
) -> WorkOrderOut:
    repo = _repo(db, tenant)
    row = _get_execution_by_code(db, tenant, execution_code)
    status = (row.status or "").upper()
    if status == "COMPLETED":
        raise WorkflowError("Cannot start a completed work order")
    if status not in ("NOT_STARTED",):
        raise WorkflowError(
            f"Work order must be Ready to start (current: {_ui_status(row.status)})"
        )
    if row.started_at:
        raise WorkflowError("Work order already started")

    rop = repo.get_by_pk(
        RoutingOperation,
        RoutingOperation.routing_operation_id,
        row.routing_operation_id,
    )
    _assert_prior_operations_complete(db, tenant, row, rop)

    operator = ((payload.operator_name if payload else None) or "").strip()
    if not operator:
        raise ValidationError("operator_name is required to start")

    selection = resolve_start_resource_selection(repo, rop, payload)
    machine_code = selection["machine_code"]
    labor_pool = selection["labor_pool_code"]
    tool_codes = selection["tool_codes"]

    meta = _meta(row)
    meta = {
        **meta,
        "operator_name": operator,
        "released_at": meta.get("released_at") or _utcnow().isoformat(),
    }
    if machine_code:
        meta["assigned_machine_code"] = machine_code
        meta["actual_machine_code"] = machine_code
    if labor_pool:
        meta["actual_labor_pool_code"] = labor_pool
    if tool_codes:
        meta["actual_tool_codes"] = tool_codes
    row.metadata_ = meta
    row.started_at = _utcnow()
    row.status = "IN_PROGRESS"
    repo.commit_refresh(row)
    return _execution_to_work_order_out(db, tenant, row, rop)


def hold_execution(
    db: Session,
    tenant: TenantContext,
    execution_code: str,
    payload: WorkOrderHoldRequest,
) -> WorkOrderOut:
    repo = _repo(db, tenant)
    row = _get_execution_by_code(db, tenant, execution_code)
    status = (row.status or "").upper()
    if status == "COMPLETED":
        raise WorkflowError("Cannot hold a completed work order")
    if status == "HOLD":
        raise WorkflowError("Work order is already on hold")
    if status not in ("NOT_STARTED", "IN_PROGRESS"):
        raise WorkflowError(f"Cannot hold work order in status '{_ui_status(row.status)}'")

    reason = (payload.reason or "").strip()
    if not reason:
        raise WorkflowError("Hold reason is required")

    meta = {**_meta(row), "hold_reason": reason}
    row.metadata_ = meta
    row.status = "HOLD"
    repo.commit_refresh(row)
    rop = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
        .first()
    )
    return _execution_to_work_order_out(db, tenant, row, rop)


def _serialize_routing_parameter(row: RoutingOperationParameter) -> dict[str, Any]:
    return {
        "parameter_code": row.parameter_code,
        "parameter_name": row.parameter_name,
        "data_type": row.data_type or "text",
        "unit": row.unit,
        "min_value": float(row.min_value) if row.min_value is not None else None,
        "max_value": float(row.max_value) if row.max_value is not None else None,
        "mandatory": bool(row.is_mandatory),
        "display_order": row.display_order,
        "source": "routing",
    }


def _parameter_defs_for_operation(
    repo: TenantRepository, routing_operation_id
) -> List[dict[str, Any]]:
    if not routing_operation_id:
        return []
    rows = (
        repo.query(RoutingOperationParameter)
        .filter(
            RoutingOperationParameter.routing_operation_id == routing_operation_id,
            RoutingOperationParameter.is_active.is_(True),
        )
        .order_by(RoutingOperationParameter.display_order.nulls_last())
        .all()
    )
    return [_serialize_routing_parameter(p) for p in rows if p.parameter_code]


def _captured_readings_for_execution(
    repo: TenantRepository, execution_id
) -> List[dict[str, Any]]:
    rows = (
        repo.query(ParameterReading)
        .filter(ParameterReading.execution_id == execution_id)
        .order_by(ParameterReading.recorded_at.asc())
        .all()
    )
    out: List[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "parameter_code": row.parameter_code,
                "parameter_name": row.parameter_name,
                "reading_value": (
                    float(row.reading_value) if row.reading_value is not None else None
                ),
                "reading_text": row.reading_text,
                "uom": row.uom,
                "recorded_at": row.recorded_at,
            }
        )
    return out


def _persist_parameter_readings(
    repo: TenantRepository,
    row: OperationExecution,
    tenant: TenantContext,
    readings: list,
    recorded_at: datetime | None = None,
) -> None:
    if not readings:
        return

    ts = recorded_at or _utcnow()
    defs = {
        p.parameter_code: p
        for p in repo.query(RoutingOperationParameter)
        .filter(RoutingOperationParameter.routing_operation_id == row.routing_operation_id)
        .all()
        if p.parameter_code
    }

    for item in readings:
        code = (item.parameter_code or "").strip()
        if not code:
            continue
        defn = defs.get(code)
        reading_value = item.reading_value
        reading_text = item.reading_text
        if reading_value is not None:
            reading_value = Decimal(str(reading_value))
        if reading_text is not None:
            reading_text = str(reading_text)

        repo.add(
            ParameterReading(
                tenant_id=tenant.tenant_id,
                execution_id=row.execution_id,
                parameter_code=code,
                parameter_name=(defn.parameter_name if defn else None) or code,
                reading_value=reading_value,
                reading_text=reading_text,
                uom=defn.unit if defn else None,
                recorded_at=ts,
            )
        )


def resume_execution(
    db: Session, tenant: TenantContext, execution_code: str
) -> WorkOrderOut:
    repo = _repo(db, tenant)
    row = _get_execution_by_code(db, tenant, execution_code)
    if (row.status or "").upper() != "HOLD":
        raise WorkflowError("Work order is not on hold")

    row.status = "IN_PROGRESS" if row.started_at else "NOT_STARTED"
    meta = {**_meta(row)}
    meta.pop("hold_reason", None)
    row.metadata_ = meta
    repo.commit_refresh(row)
    rop = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
        .first()
    )
    return _execution_to_work_order_out(db, tenant, row, rop)


def complete_execution(
    db: Session,
    tenant: TenantContext,
    execution_code: str,
    payload: WorkOrderCompleteRequest,
) -> WorkOrderOut:
    repo = _repo(db, tenant)
    row = _get_execution_by_code(db, tenant, execution_code)
    if not row.started_at:
        raise WorkflowError("Work order must be started before completion")
    if row.completed_at or (row.status or "").upper() == "COMPLETED":
        raise WorkflowError("Work order already completed")

    machine_code = (payload.machine_id or "").strip() if payload.machine_id else ""
    prior_meta = _meta(row)
    meta = {
        **prior_meta,
        "actual_output_quantity": (
            str(payload.actual_output_quantity)
            if payload.actual_output_quantity is not None
            else None
        ),
        "scrap_quantity": (
            str(payload.scrap_quantity) if payload.scrap_quantity is not None else None
        ),
        "rework_quantity": (
            str(payload.rework_quantity) if payload.rework_quantity is not None else None
        ),
        "operator_name": (
            str(payload.operator_name).strip()
            if payload.operator_name
            else prior_meta.get("operator_name")
        ),
        "actual_machine_code": machine_code or prior_meta.get("assigned_machine_code"),
        "downtime_minutes": (
            str(payload.downtime_minutes)
            if payload.downtime_minutes is not None
            else None
        ),
    }
    if payload.parameter_readings:
        meta["captured_parameter_count"] = len(payload.parameter_readings)
    row.metadata_ = meta
    row.completed_at = _utcnow()
    row.status = "COMPLETED"
    _persist_parameter_readings(
        repo,
        row,
        tenant,
        payload.parameter_readings or [],
        recorded_at=row.completed_at,
    )
    repo.commit_refresh(row)
    rop = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
        .first()
    )
    return _execution_to_work_order_out(db, tenant, row, rop)


def append_execution_parameter_readings(
    db: Session,
    tenant: TenantContext,
    execution_code: str,
    readings: List[ParameterReadingInput],
) -> WorkOrderOut:
    """Record additional parameter readings after an operation is completed."""
    repo = _repo(db, tenant)
    row = _get_execution_by_code(db, tenant, execution_code)
    if (row.status or "").upper() != "COMPLETED":
        raise WorkflowError(
            "Additional readings can only be added after the operation is completed"
        )
    if not readings:
        raise ValidationError("parameter_readings is required")
    _persist_parameter_readings(repo, row, tenant, readings)
    repo.commit_refresh(row)
    rop = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
        .first()
    )
    return _execution_to_work_order_out(db, tenant, row, rop)
