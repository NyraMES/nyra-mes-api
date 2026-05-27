"""Production-schedule service.

Workflow rule: a lot can only be scheduled once its latest feasibility
gate has been ``OK``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, WorkflowError
from app.models.order import CustomerOrderLine
from app.models.part import Part
from app.models.production import ProductionLot, ProductionOrder
from app.models.resource import Machine, WorkCenter
from app.models.routing import (
    OperationResourceRequirement,
    Routing,
    RoutingOperation,
)
from app.models.schedule import ProductionSchedule
from app.models.work_order import WorkOrder
from app.schemas.schedule import ScheduleCreate, ScheduleOut
from app.services import feasibility_service, resolver
from app.utils.ids import generate_business_id
from app.utils.time import utcnow


def _to_out(db: Session, row: ProductionSchedule) -> ScheduleOut:
    return ScheduleOut(
        id=row.id,
        schedule_id=row.schedule_code,
        lot_id=resolver.lot_code(db, row.lot_id) if row.lot_id else None,
        operation_id=(
            resolver.operation_code(db, row.routing_operation_id)
            if row.routing_operation_id
            else None
        ),
        planned_start_time=row.planned_start_time,
        planned_end_time=row.planned_end_time,
        assigned_work_center_id=(
            resolver.work_center_code(db, row.assigned_work_center_id)
            if row.assigned_work_center_id
            else None
        ),
        assigned_machine_id=(
            resolver.machine_code(db, row.assigned_machine_id)
            if row.assigned_machine_id
            else None
        ),
        schedule_status=row.schedule_status,
        created_at=row.created_at,
    )


def list_schedules(db: Session) -> List[ScheduleOut]:
    rows = db.query(ProductionSchedule).order_by(ProductionSchedule.id).all()
    return [_to_out(db, r) for r in rows]


def get_schedule(db: Session, code: str) -> ScheduleOut:
    row = (
        db.query(ProductionSchedule)
        .filter(ProductionSchedule.schedule_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Schedule '{code}' not found")
    return _to_out(db, row)


def create_schedule(db: Session, payload: ScheduleCreate) -> ScheduleOut:
    if not feasibility_service.is_ready_for_scheduling(db, payload.lot_id):
        raise WorkflowError(
            "Lot is not feasibility-ready; run /feasibility/{lot_id} first",
            details={"lot_id": payload.lot_id},
        )

    code = (payload.schedule_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_schedule,
        sequence="trn.schedule_seq",
        fallback_table="trn.production_schedule",
        fallback_column="schedule_code",
    )
    if (
        db.query(ProductionSchedule)
        .filter(ProductionSchedule.schedule_code == code)
        .first()
    ):
        raise ConflictError(f"Schedule '{code}' already exists")

    lot_pk = resolver.lot_id(db, payload.lot_id)
    routing_pk = (
        resolver.routing_operation_id(db, payload.operation_id)
        if payload.operation_id
        else None
    )

    row = ProductionSchedule(
        schedule_code=code,
        lot_id=lot_pk,
        routing_operation_id=routing_pk,
        planned_start_time=payload.planned_start_time,
        planned_end_time=payload.planned_end_time,
        assigned_work_center_id=(
            resolver.work_center_id(db, payload.assigned_work_center_id)
            if payload.assigned_work_center_id
            else None
        ),
        assigned_machine_id=(
            resolver.machine_id(db, payload.assigned_machine_id)
            if payload.assigned_machine_id
            else None
        ),
        schedule_status=payload.schedule_status or "Scheduled",
    )
    db.add(row)
    try:
        db.flush()
        if routing_pk:
            wo = (
                db.query(WorkOrder)
                .filter(
                    WorkOrder.lot_id == lot_pk,
                    WorkOrder.routing_operation_id == routing_pk,
                )
                .first()
            )
            if not wo:
                wo_code = generate_business_id(
                    db,
                    prefix=settings.id_prefix_work_order,
                    sequence="trn.work_order_seq",
                    fallback_table="trn.work_order",
                    fallback_column="work_order_code",
                )
                wo = WorkOrder(
                    work_order_code=wo_code,
                    schedule_id=row.id,
                    lot_id=lot_pk,
                    routing_operation_id=routing_pk,
                    work_order_status="Released",
                    released_at=utcnow(),
                )
                db.add(wo)
            else:
                wo.schedule_id = row.id
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Schedule '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _to_out(db, row)


# ---------------------------------------------------------------------------
# Schedule plan (auto-fill helper for the scheduling UI)
# ---------------------------------------------------------------------------

def get_schedule_plan(db: Session, lot_code: str) -> Dict[str, Any]:
    """Return the pre-filled scheduling plan for a lot.

    Walks Lot -> ProductionOrder -> OrderLine -> Part -> active Routing,
    then for each operation in sequence:
      - estimates duration as ``cycle_time x lot_quantity``
      - suggests a machine (mandatory ``machine`` resource requirement)
      - resolves that machine's work center
      - flags whether the operation is already scheduled for this lot.

    The scheduling UI consumes this directly so the user just confirms
    the suggestions and clicks Schedule.
    """

    lot = db.query(ProductionLot).filter(ProductionLot.lot_code == lot_code).first()
    if not lot:
        raise NotFoundError(f"Production lot '{lot_code}' not found")

    po = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.id == lot.production_order_id)
        .first()
        if lot.production_order_id
        else None
    )
    if not po or not po.order_line_id:
        raise WorkflowError(
            f"Lot '{lot_code}' has no production order linkage; "
            "cannot derive its routing"
        )

    line = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.id == po.order_line_id)
        .first()
    )
    if not line or not line.part_id:
        raise WorkflowError(
            f"Lot '{lot_code}' order line has no part; cannot derive routing"
        )

    part = db.query(Part).filter(Part.id == line.part_id).first()
    routing = (
        db.query(Routing)
        .filter(Routing.part_id == line.part_id, Routing.is_active.is_(True))
        .order_by(Routing.id.desc())
        .first()
    )
    if not routing:
        raise WorkflowError(
            f"No active routing defined for part {part.part_code if part else line.part_id}",
            details={"hint": "Create a routing in Master Data -> Routings"},
        )

    operations = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )

    # Existing schedules for this lot (so the UI can flag already-scheduled
    # operations and skip them on the "Schedule all" path)
    existing = (
        db.query(ProductionSchedule.routing_operation_id, ProductionSchedule.schedule_code)
        .filter(ProductionSchedule.lot_id == lot.id)
        .all()
    )
    scheduled_op_codes: Dict[int, str] = {
        op_id: sched_code for (op_id, sched_code) in existing if op_id is not None
    }

    lot_qty = Decimal(str(lot.lot_quantity or 0))
    plan_ops: List[Dict[str, Any]] = []
    for op in operations:
        cycle = Decimal(str(op.standard_cycle_time_minutes or 0))
        estimated_minutes = float(cycle * lot_qty) if cycle > 0 and lot_qty > 0 else None

        suggested_machine_code: str | None = None
        suggested_machine_name: str | None = None
        suggested_wc_code: str | None = None
        suggested_wc_name: str | None = None

        req = (
            db.query(OperationResourceRequirement)
            .filter(
                OperationResourceRequirement.routing_operation_id == op.id,
                OperationResourceRequirement.required_resource_type == "machine",
                OperationResourceRequirement.is_mandatory.is_(True),
            )
            .order_by(OperationResourceRequirement.id)
            .first()
        )
        if req and req.required_resource_id:
            mach = (
                db.query(Machine).filter(Machine.id == req.required_resource_id).first()
            )
            if mach:
                suggested_machine_code = mach.machine_code
                suggested_machine_name = mach.machine_name
                if mach.work_center_id:
                    wc = (
                        db.query(WorkCenter)
                        .filter(WorkCenter.id == mach.work_center_id)
                        .first()
                    )
                    if wc:
                        suggested_wc_code = wc.work_center_code
                        suggested_wc_name = wc.work_center_name

        plan_ops.append(
            {
                "operation_id": op.operation_code,
                "operation_sequence": op.operation_sequence,
                "operation_name": op.operation_name,
                "standard_cycle_time_minutes": (
                    float(op.standard_cycle_time_minutes)
                    if op.standard_cycle_time_minutes is not None
                    else None
                ),
                "estimated_duration_minutes": estimated_minutes,
                "inspection_required": bool(op.inspection_required),
                "suggested_machine_id": suggested_machine_code,
                "suggested_machine_name": suggested_machine_name,
                "suggested_work_center_id": suggested_wc_code,
                "suggested_work_center_name": suggested_wc_name,
                "existing_schedule_id": scheduled_op_codes.get(op.id),
                "already_scheduled": op.id in scheduled_op_codes,
            }
        )

    return {
        "lot_id": lot_code,
        "lot_quantity": float(lot_qty),
        "lot_status": lot.status,
        "production_order_id": resolver.production_order_code(db, po.id),
        "part_id": part.part_code if part else None,
        "part_name": part.part_name if part else None,
        "routing_id": routing.routing_code,
        "routing_version": routing.routing_version,
        "operations": plan_ops,
    }
