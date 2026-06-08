"""Production scheduling for nyra_mes_core.

Schedules are stored as ``exec.operation_execution`` rows with
``status='NOT_STARTED'`` and schedule details in ``metadata`` (no separate
``production_schedule`` table).  This avoids a DB migration while matching
the legacy scheduling UI contract.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError, WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrderLine,
    Equipment,
    OperationExecution,
    OperationResourceRequirement,
    Product,
    ProductionLot,
    ProductionOrder,
    Resource,
    Routing,
    RoutingOperation,
)
from app.schemas.mes_core.schemas import (
    ScheduleCreate,
    ScheduleOut,
    SchedulePlanOut,
)
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.feasibility import (
    assert_machine_available_for_schedule,
    assert_no_schedule_conflict,
    is_ready_for_scheduling,
)
from app.services.mes_core.ids import resolve_business_code

_SCHEDULE_META_FLAG = "is_production_schedule"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _schedule_meta(row: OperationExecution) -> dict[str, Any]:
    meta = row.metadata_ or {}
    return meta if isinstance(meta, dict) else {}


def _is_schedule_row(row: OperationExecution) -> bool:
    meta = _schedule_meta(row)
    return bool(meta.get(_SCHEDULE_META_FLAG) or meta.get("schedule_code"))


def _schedule_out(
    db: Session,
    tenant: TenantContext,
    row: OperationExecution,
) -> ScheduleOut:
    meta = _schedule_meta(row)
    lot = (
        _repo(db, tenant)
        .query(ProductionLot)
        .filter(ProductionLot.production_lot_id == row.production_lot_id)
        .first()
    )
    op = (
        _repo(db, tenant)
        .query(RoutingOperation)
        .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
        .first()
    )
    schedule_code = meta.get("schedule_code") or row.execution_code
    return ScheduleOut(
        schedule_id=schedule_code,
        lot_id=lot.lot_code if lot else None,
        operation_id=op.operation_code if op else None,
        planned_start_time=_parse_dt(meta.get("planned_start_time")),
        planned_end_time=_parse_dt(meta.get("planned_end_time")),
        assigned_work_center_id=meta.get("assigned_work_center_code"),
        assigned_machine_id=meta.get("assigned_machine_code"),
        schedule_status=meta.get("schedule_status") or "Scheduled",
        created_at=row.created_at,
    )


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


def _iso_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def list_schedules(db: Session, tenant: TenantContext) -> List[ScheduleOut]:
    rows = (
        _repo(db, tenant)
        .query(OperationExecution)
        .order_by(OperationExecution.created_at.desc())
        .all()
    )
    return [_schedule_out(db, tenant, r) for r in rows if _is_schedule_row(r)]


def _resolve_lot(db: Session, tenant: TenantContext, lot_code: str) -> ProductionLot:
    return _repo(db, tenant).get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)


def _resolve_operation(
    db: Session, tenant: TenantContext, operation_code: str
) -> RoutingOperation:
    return _repo(db, tenant).get_by_code(
        RoutingOperation, RoutingOperation.operation_code, operation_code
    )


def _optional_by_code(
    db: Session, tenant: TenantContext, model, code_column, code_value: str
):
    code = (code_value or "").strip()
    if not code:
        return None
    try:
        return _repo(db, tenant).get_by_code(model, code_column, code)
    except NotFoundError:
        return None


def create_schedule(
    db: Session, tenant: TenantContext, payload: ScheduleCreate
) -> ScheduleOut:
    if not is_ready_for_scheduling(db, tenant, payload.lot_id):
        raise WorkflowError(
            "Lot is not feasibility-ready; run feasibility check first",
            details={"lot_id": payload.lot_id},
        )

    repo = _repo(db, tenant)
    lot = _resolve_lot(db, tenant, payload.lot_id)
    if not payload.operation_id:
        raise ValidationError("operation_id is required")

    operation = _resolve_operation(db, tenant, payload.operation_id)

    existing = (
        repo.query(OperationExecution)
        .filter(
            OperationExecution.production_lot_id == lot.production_lot_id,
            OperationExecution.routing_operation_id == operation.routing_operation_id,
        )
        .all()
    )
    for row in existing:
        if _is_schedule_row(row):
            meta = _schedule_meta(row)
            raise ConflictError(
                f"Operation '{payload.operation_id}' is already scheduled for lot "
                f"'{payload.lot_id}' (schedule {meta.get('schedule_code')})"
            )

    equipment = _optional_by_code(
        db, tenant, Equipment, Equipment.equipment_code, payload.assigned_machine_id or ""
    )
    machine_resource = None
    if payload.assigned_machine_id and not equipment:
        machine_resource = _optional_by_code(
            db, tenant, Resource, Resource.resource_code, payload.assigned_machine_id
        )
    if payload.assigned_machine_id and not equipment and not machine_resource:
        raise NotFoundError(
            f"Machine or resource '{payload.assigned_machine_id}' not found"
        )

    machine_code = (payload.assigned_machine_id or "").strip()
    if machine_code:
        assert_machine_available_for_schedule(
            equipment=equipment,
            resource=machine_resource,
            machine_code=machine_code,
        )
        if payload.planned_start_time and payload.planned_end_time:
            assert_no_schedule_conflict(
                repo,
                machine_code=machine_code,
                planned_start=payload.planned_start_time,
                planned_end=payload.planned_end_time,
                exclude_lot_id=lot.production_lot_id,
            )

    work_center = _optional_by_code(
        db,
        tenant,
        Resource,
        Resource.resource_code,
        payload.assigned_work_center_id or "",
    )
    if payload.assigned_work_center_id and not work_center:
        raise NotFoundError(
            f"Work center / resource '{payload.assigned_work_center_id}' not found"
        )

    schedule_code = resolve_business_code(
        db,
        provided=payload.schedule_id,
        entity="schedule",
    )
    execution_code = resolve_business_code(
        db,
        provided=None,
        entity="operation_execution",
    )

    metadata: Dict[str, Any] = {
        _SCHEDULE_META_FLAG: True,
        "schedule_code": schedule_code,
        "schedule_status": payload.schedule_status or "Scheduled",
        "planned_start_time": _iso_dt(payload.planned_start_time),
        "planned_end_time": _iso_dt(payload.planned_end_time),
        "assigned_machine_code": payload.assigned_machine_id,
        "assigned_work_center_code": payload.assigned_work_center_id,
    }

    row = repo.add(
        OperationExecution(
            execution_code=execution_code,
            production_lot_id=lot.production_lot_id,
            routing_operation_id=operation.routing_operation_id,
            equipment_id=equipment.equipment_id if equipment else None,
            status="NOT_STARTED",
            metadata_=metadata,
        )
    )
    return _schedule_out(db, tenant, repo.commit_refresh(row))


def get_schedule_plan(
    db: Session, tenant: TenantContext, lot_code: str
) -> SchedulePlanOut:
    repo = _repo(db, tenant)
    lot = _resolve_lot(db, tenant, lot_code)

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

    routing = (
        repo.query(Routing)
        .filter(Routing.product_id == product.product_id, Routing.is_active.is_(True))
        .order_by(Routing.routing_version.desc())
        .first()
    )
    if not routing:
        raise WorkflowError(
            f"No active routing found for product '{product.product_code}'",
            details={"lot_id": lot_code, "product_code": product.product_code},
        )

    operations = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )

    scheduled_by_op: Dict[str, str] = {}
    existing_rows = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot.production_lot_id)
        .all()
    )
    for ex in existing_rows:
        if not _is_schedule_row(ex):
            continue
        op = (
            repo.query(RoutingOperation)
            .filter(RoutingOperation.routing_operation_id == ex.routing_operation_id)
            .first()
        )
        if op:
            meta = _schedule_meta(ex)
            scheduled_by_op[op.operation_code] = meta.get("schedule_code") or ex.execution_code

    lot_qty = float(lot.lot_quantity)
    plan_ops = []
    for op in operations:
        cycle = float(op.standard_cycle_min) if op.standard_cycle_min is not None else None
        estimated = cycle * lot_qty if cycle is not None else None

        suggested_machine_code: Optional[str] = None
        suggested_machine_name: Optional[str] = None
        suggested_wc_code: Optional[str] = None
        suggested_wc_name: Optional[str] = None

        req = (
            repo.query(OperationResourceRequirement)
            .filter(
                OperationResourceRequirement.routing_operation_id
                == op.routing_operation_id,
                OperationResourceRequirement.requirement_type == "PRIMARY",
            )
            .first()
        )
        if req:
            resource = (
                repo.query(Resource)
                .filter(Resource.resource_id == req.resource_id)
                .first()
            )
            if resource:
                suggested_wc_code = resource.resource_code
                suggested_wc_name = resource.resource_name
                equip = (
                    repo.query(Equipment)
                    .filter(Equipment.resource_id == resource.resource_id)
                    .first()
                )
                if equip:
                    suggested_machine_code = equip.equipment_code
                    suggested_machine_name = equip.equipment_name

        if not suggested_machine_code:
            fallback_equip = (
                repo.query(Equipment).order_by(Equipment.equipment_code).first()
            )
            if fallback_equip:
                suggested_machine_code = fallback_equip.equipment_code
                suggested_machine_name = fallback_equip.equipment_name
                if fallback_equip.resource_id and not suggested_wc_code:
                    wc = (
                        repo.query(Resource)
                        .filter(Resource.resource_id == fallback_equip.resource_id)
                        .first()
                    )
                    if wc:
                        suggested_wc_code = wc.resource_code
                        suggested_wc_name = wc.resource_name
            elif not suggested_wc_code:
                fallback_res = (
                    repo.query(Resource)
                    .filter(Resource.resource_type.in_(("MACHINE", "WORKCELL", "LINE")))
                    .order_by(Resource.resource_code)
                    .first()
                )
                if fallback_res:
                    suggested_machine_code = fallback_res.resource_code
                    suggested_machine_name = fallback_res.resource_name
                    suggested_wc_code = fallback_res.resource_code
                    suggested_wc_name = fallback_res.resource_name

        meta = op.metadata_ if isinstance(op.metadata_, dict) else {}
        plan_ops.append(
            {
                "operation_id": op.operation_code,
                "operation_sequence": op.operation_sequence,
                "operation_name": op.operation_name,
                "standard_cycle_time_minutes": cycle,
                "estimated_duration_minutes": estimated,
                "inspection_required": bool(meta.get("inspection_required")),
                "suggested_machine_id": suggested_machine_code,
                "suggested_machine_name": suggested_machine_name,
                "suggested_work_center_id": suggested_wc_code,
                "suggested_work_center_name": suggested_wc_name,
                "existing_schedule_id": scheduled_by_op.get(op.operation_code),
                "already_scheduled": op.operation_code in scheduled_by_op,
            }
        )

    return SchedulePlanOut(
        lot_id=lot_code,
        lot_quantity=lot_qty,
        lot_status=lot.status,
        production_order_id=po.production_order_code,
        part_id=product.product_code,
        part_name=product.product_name,
        routing_id=routing.routing_code,
        routing_version=routing.routing_version,
        operations=plan_ops,
    )
