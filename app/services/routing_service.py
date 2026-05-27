"""Routing and routing-operation service."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, WorkflowError
from app.models.routing import (
    OperationResourceRequirement,
    Routing,
    RoutingOperation,
)
from app.schemas.routing import (
    OperationResourceRequirementCreate,
    OperationResourceRequirementOut,
    RoutingCreate,
    RoutingOperationCreate,
    RoutingOperationEntryCreate,
    RoutingOperationOut,
    RoutingOperationUpdate,
    RoutingOut,
    RoutingWithOperationsCreate,
    RoutingWithOperationsOut,
    PartRoutingOut,
)
from app.services import data_capture_service, process_service, resolver
from app.utils.ids import generate_business_id


def _routing_to_out(db: Session, row: Routing) -> RoutingOut:
    return RoutingOut(
        id=row.id,
        routing_id=row.routing_code,
        part_id=resolver.part_code(db, row.part_id) if row.part_id else None,
        routing_version=row.routing_version,
        process_type=row.process_type,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def _operation_to_out(db: Session, row: RoutingOperation) -> RoutingOperationOut:
    suggested = None
    if row.routing_id:
        suggested = data_capture_service.next_operation_sequence(db, row.routing_id)
    data_capture_templates = (
        data_capture_service.get_process_form_templates(db, row.process_id)
        if row.process_id
        else []
    )
    return RoutingOperationOut(
        id=row.id,
        operation_id=row.operation_code,
        routing_operation_id=row.operation_code,
        operation_code=row.operation_code,
        routing_id=resolver.routing_code_for(db, row.routing_id) if row.routing_id else None,
        operation_sequence=row.operation_sequence,
        operation_name=row.operation_name,
        process_id=row.process_id,
        standard_cycle_time_minutes=row.standard_cycle_time_minutes,
        inspection_required=row.inspection_required,
        created_at=row.created_at,
        suggested_next_operation_sequence=suggested,
        data_capture_templates=data_capture_templates or None,
    )


def _req_to_out(db: Session, row: OperationResourceRequirement) -> OperationResourceRequirementOut:
    return OperationResourceRequirementOut(
        id=row.id,
        operation_id=resolver.operation_code(db, row.routing_operation_id) if row.routing_operation_id else None,
        required_resource_type=row.required_resource_type,
        required_resource_id=row.required_resource_id,
        required_quantity=row.required_quantity,
        is_mandatory=row.is_mandatory,
        created_at=row.created_at,
    )


def list_routings(db: Session) -> List[RoutingOut]:
    rows = db.query(Routing).order_by(Routing.id).all()
    return [_routing_to_out(db, r) for r in rows]


def get_routing(db: Session, code: str) -> RoutingOut:
    row = db.query(Routing).filter(Routing.routing_code == code).first()
    if not row:
        raise NotFoundError(f"Routing '{code}' not found")
    return _routing_to_out(db, row)


def list_operations(db: Session, routing_code: str) -> List[RoutingOperationOut]:
    rid = resolver.routing_id(db, routing_code)
    rows = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == rid)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    return [_operation_to_out(db, r) for r in rows]


def list_requirements(db: Session, operation_code: str) -> List[OperationResourceRequirementOut]:
    oid = resolver.routing_operation_id(db, operation_code)
    rows = (
        db.query(OperationResourceRequirement)
        .filter(OperationResourceRequirement.routing_operation_id == oid)
        .order_by(OperationResourceRequirement.id)
        .all()
    )
    return [_req_to_out(db, r) for r in rows]


def create_routing(db: Session, payload: RoutingCreate) -> RoutingOut:
    code = (payload.routing_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_routing,
        sequence="mst.routing_seq",
        fallback_table="mst.routing",
        fallback_column="routing_code",
    )
    if db.query(Routing).filter(Routing.routing_code == code).first():
        raise ConflictError(f"Routing '{code}' already exists")

    part_pk = resolver.part_id(db, payload.part_id)
    row = Routing(
        routing_code=code,
        part_id=part_pk,
        routing_version=payload.routing_version,
        process_type=payload.process_type,
        is_active=payload.is_active,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Routing '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _routing_to_out(db, row)


def _validate_process_id(db: Session, process_id: Optional[str]) -> None:
    if not process_id:
        return
    process_service.get_process_row(db, process_id)


def create_operation(
    db: Session, payload: RoutingOperationCreate
) -> RoutingOperationOut:
    routing_pk = resolver.routing_id(db, payload.routing_id)
    _validate_process_id(db, payload.process_id)

    operation_sequence = payload.operation_sequence
    if operation_sequence is None:
        operation_sequence = data_capture_service.next_operation_sequence(db, routing_pk)
    data_capture_service._ensure_unique_operation_sequence(
        db, routing_pk, operation_sequence
    )

    code = (payload.operation_id or "").strip() or generate_business_id(
        db,
        prefix="OP",
        sequence="mst.operation_seq",
        fallback_table="mst.routing_operation",
        fallback_column="operation_code",
    )
    if (
        db.query(RoutingOperation)
        .filter(RoutingOperation.operation_code == code)
        .first()
    ):
        raise ConflictError(f"Routing operation '{code}' already exists")

    row = RoutingOperation(
        operation_code=code,
        routing_id=routing_pk,
        operation_sequence=operation_sequence,
        operation_name=payload.operation_name,
        process_id=payload.process_id,
        standard_cycle_time_minutes=payload.standard_cycle_time_minutes,
        inspection_required=payload.inspection_required,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Routing operation '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _operation_to_out(db, row)


def _next_operation_code(db: Session) -> str:
    return generate_business_id(
        db,
        prefix="OP",
        sequence="mst.operation_seq",
        fallback_table="mst.routing_operation",
        fallback_column="operation_code",
    )


def create_routing_with_operations(
    db: Session, payload: RoutingWithOperationsCreate
) -> RoutingWithOperationsOut:
    """Atomically insert a ``Routing`` plus all its operations.

    The frontend's Routing Master uses this so the editor flow is "build
    the whole routing, then click Save once" rather than POST-and-poll
    between every operation.
    """
    code = (payload.routing_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_routing,
        sequence="mst.routing_seq",
        fallback_table="mst.routing",
        fallback_column="routing_code",
    )
    if db.query(Routing).filter(Routing.routing_code == code).first():
        raise ConflictError(f"Routing '{code}' already exists")

    part_pk = resolver.part_id(db, payload.part_id)
    routing = Routing(
        routing_code=code,
        part_id=part_pk,
        routing_version=payload.routing_version,
        process_type=payload.process_type,
        is_active=payload.is_active,
    )
    db.add(routing)
    db.flush()  # need routing.id for operation FKs

    op_rows: List[RoutingOperation] = []
    seen_sequences: set[int] = set()
    for op_in in payload.operations:
        _validate_process_id(db, op_in.process_id)
        operation_sequence = op_in.operation_sequence
        if operation_sequence is None:
            operation_sequence = data_capture_service.next_operation_sequence(
                db, routing.id
            )
        if operation_sequence in seen_sequences:
            raise ConflictError(
                f"Duplicate operation_sequence {operation_sequence} in request"
            )
        seen_sequences.add(operation_sequence)
        data_capture_service._ensure_unique_operation_sequence(
            db, routing.id, operation_sequence
        )

        op_code = (op_in.operation_id or "").strip() or _next_operation_code(db)
        if (
            db.query(RoutingOperation)
            .filter(RoutingOperation.operation_code == op_code)
            .first()
        ):
            raise ConflictError(f"Routing operation '{op_code}' already exists")
        row = RoutingOperation(
            operation_code=op_code,
            routing_id=routing.id,
            operation_sequence=operation_sequence,
            operation_name=op_in.operation_name,
            process_id=op_in.process_id,
            standard_cycle_time_minutes=op_in.standard_cycle_time_minutes,
            inspection_required=op_in.inspection_required,
        )
        db.add(row)
        op_rows.append(row)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Routing '{code}' could not be committed: {exc.orig}")
    db.refresh(routing)
    for r in op_rows:
        db.refresh(r)

    return RoutingWithOperationsOut(
        routing=_routing_to_out(db, routing),
        operations=[_operation_to_out(db, r) for r in op_rows],
    )


def list_routings_for_part(db: Session, part_code: str) -> List[RoutingOut]:
    part_pk = resolver.part_id(db, part_code)
    rows = (
        db.query(Routing)
        .filter(Routing.part_id == part_pk)
        .order_by(Routing.id)
        .all()
    )
    return [_routing_to_out(db, r) for r in rows]


def get_part_routing(db: Session, part_code: str) -> PartRoutingOut:
    """Return the active routing and sequenced operations for a part."""
    part_pk = resolver.part_id(db, part_code)
    routing = (
        db.query(Routing)
        .filter(Routing.part_id == part_pk, Routing.is_active.is_(True))
        .order_by(Routing.id.desc())
        .first()
    )
    if not routing:
        raise NotFoundError(f"No active routing found for part '{part_code}'")

    operations = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    return PartRoutingOut(
        routing=_routing_to_out(db, routing),
        operations=[_operation_to_out(db, op) for op in operations],
    )


def add_operation_to_routing(
    db: Session, routing_code: str, payload: RoutingOperationEntryCreate
) -> RoutingOperationOut:
    create_payload = RoutingOperationCreate(
        routing_id=routing_code,
        operation_id=payload.operation_id,
        operation_sequence=payload.operation_sequence,
        operation_name=payload.operation_name,
        process_id=payload.process_id,
        standard_cycle_time_minutes=payload.standard_cycle_time_minutes,
        inspection_required=payload.inspection_required,
    )
    return create_operation(db, create_payload)


def update_routing_operation(
    db: Session, operation_code: str, payload: RoutingOperationUpdate
) -> RoutingOperationOut:
    row = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.operation_code == operation_code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Routing operation '{operation_code}' not found")

    if payload.process_id is not None:
        if payload.process_id == "":
            row.process_id = None
        else:
            _validate_process_id(db, payload.process_id)
            row.process_id = payload.process_id

    if payload.operation_sequence is not None:
        data_capture_service._ensure_unique_operation_sequence(
            db,
            row.routing_id,
            payload.operation_sequence,
            exclude_id=row.id,
        )
        row.operation_sequence = payload.operation_sequence

    if payload.operation_name is not None:
        row.operation_name = payload.operation_name.strip()
    if payload.standard_cycle_time_minutes is not None:
        row.standard_cycle_time_minutes = payload.standard_cycle_time_minutes
    if payload.inspection_required is not None:
        row.inspection_required = payload.inspection_required

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Routing operation '{operation_code}' could not be updated: {exc.orig}"
        ) from exc
    db.refresh(row)
    return _operation_to_out(db, row)


def delete_routing_operation(db: Session, operation_code: str) -> None:
    from app.models.work_order import WorkOrder

    row = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.operation_code == operation_code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Routing operation '{operation_code}' not found")

    in_use = (
        db.query(WorkOrder)
        .filter(WorkOrder.routing_operation_id == row.id)
        .first()
    )
    if in_use:
        raise WorkflowError(
            f"Routing operation '{operation_code}' is referenced by work orders and cannot be deleted"
        )

    db.delete(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Routing operation '{operation_code}' could not be deleted: {exc.orig}"
        ) from exc


def _resolve_lot_routing_context(db: Session, lot_code: str):
    """Return ``(lot, part_code, part_name, routing, routing_operations)``."""
    from app.models.order import CustomerOrderLine
    from app.models.part import Part
    from app.models.production import ProductionLot, ProductionOrder

    lot = (
        db.query(ProductionLot)
        .filter(ProductionLot.lot_code == lot_code)
        .first()
    )
    if not lot:
        raise NotFoundError(f"Production lot '{lot_code}' not found")
    if not lot.production_order_id:
        raise WorkflowError(f"Lot '{lot_code}' has no production order")

    po = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.id == lot.production_order_id)
        .first()
    )
    if not po or not po.order_line_id:
        raise WorkflowError(f"Lot '{lot_code}': cannot resolve part for routing")

    line = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.id == po.order_line_id)
        .first()
    )
    if not line or not line.part_id:
        raise WorkflowError(f"Lot '{lot_code}': order-line has no part")

    part = db.query(Part).filter(Part.id == line.part_id).first()
    part_code = part.part_code if part else resolver.part_code(db, line.part_id)
    part_name = part.part_name if part else None

    routing = (
        db.query(Routing)
        .filter(Routing.part_id == line.part_id, Routing.is_active.is_(True))
        .order_by(Routing.id.desc())
        .first()
    )
    if not routing:
        raise WorkflowError(
            f"No active routing defined for part {part_code}",
            details={"hint": "Create a routing in Master Data → Routings for this part"},
        )

    operations = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    if not operations:
        raise WorkflowError(f"Routing '{routing.routing_code}' has no operations")

    return lot, part_code, part_name, routing, operations


def get_lot_routing_plan(db: Session, lot_code: str) -> dict:
    """Preview the active routing for a lot and whether work orders exist.

    Used by the Routing Flow UI — independent of feasibility gating.
    """
    from app.models.process import ProcessLibrary
    from app.models.work_order import WorkOrder

    lot, part_code, part_name, routing, operations = _resolve_lot_routing_context(
        db, lot_code
    )

    existing_wos = (
        db.query(WorkOrder)
        .filter(WorkOrder.lot_id == lot.id)
        .all()
    )
    wo_by_op = {
        wo.routing_operation_id: wo
        for wo in existing_wos
        if wo.routing_operation_id is not None
    }

    process_ids = {op.process_id for op in operations if op.process_id}
    process_names: dict[str, str] = {}
    if process_ids:
        for pid, pname in (
            db.query(ProcessLibrary.process_id, ProcessLibrary.process_name)
            .filter(ProcessLibrary.process_id.in_(process_ids))
            .all()
        ):
            process_names[pid] = pname

    plan_ops = []
    generated_count = 0
    for op in operations:
        wo = wo_by_op.get(op.id)
        if wo:
            generated_count += 1
        ui_status = None
        if wo:
            status = (wo.work_order_status or "").strip().lower()
            if status == "released":
                ui_status = "Ready"
            elif status in ("inprogress", "in progress"):
                ui_status = "In Progress"
            elif status == "completed":
                ui_status = "Completed"
            else:
                ui_status = wo.work_order_status or "Pending"

        plan_ops.append(
            {
                "operation_id": op.operation_code,
                "operation_code": op.operation_code,
                "operation_sequence": op.operation_sequence,
                "operation_name": op.operation_name,
                "process_id": op.process_id,
                "process_name": process_names.get(op.process_id) if op.process_id else None,
                "work_order_id": wo.work_order_code if wo else None,
                "work_order_generated": wo is not None,
                "status": ui_status or ("Pending" if not wo else "Ready"),
            }
        )

    pending_count = len(plan_ops) - generated_count
    return {
        "lot_id": lot_code,
        "part_id": part_code,
        "part_name": part_name,
        "routing_id": routing.routing_code,
        "routing_version": routing.routing_version,
        "operations": plan_ops,
        "total_operations": len(plan_ops),
        "generated_work_orders": generated_count,
        "pending_work_orders": pending_count,
        "can_generate": pending_count > 0,
        "routing_complete": pending_count == 0 and len(plan_ops) > 0,
    }


def generate_lot_route(db: Session, lot_code: str):
    """Materialise the lot's route as ``work_order`` rows.

    In the legacy schema this populated ``trn.lot_operation_execution``;
    the new DB doesn't have that table, so we map every operation in the
    active routing onto a Released work order under the lot.
    """
    from app.core.config import settings
    from app.models.work_order import WorkOrder
    from app.utils.ids import generate_business_id
    from app.utils.time import utcnow

    lot, _part_code, _part_name, _routing, operations = _resolve_lot_routing_context(
        db, lot_code
    )

    created = []
    for op in operations:
        existing = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.lot_id == lot.id,
                WorkOrder.routing_operation_id == op.id,
            )
            .first()
        )
        if existing:
            continue
        wo_code = generate_business_id(
            db,
            prefix=settings.id_prefix_work_order,
            sequence="trn.work_order_seq",
            fallback_table="trn.work_order",
            fallback_column="work_order_code",
        )
        wo = WorkOrder(
            work_order_code=wo_code,
            lot_id=lot.id,
            routing_operation_id=op.id,
            work_order_status="Released",
            released_at=utcnow(),
        )
        db.add(wo)
        created.append((op, wo, wo_code))
    db.commit()

    from app.services import feasibility_service

    feasibility = feasibility_service.check_feasibility(db, lot_code)

    return [
        {
            "work_order_id": wo_code,
            "operation_sequence": op.operation_sequence,
            "operation_code": op.operation_code,
            "operation_name": op.operation_name,
            "status": "Released",
        }
        for (op, _wo, wo_code) in created
    ], feasibility


def add_requirement(
    db: Session, payload: OperationResourceRequirementCreate
) -> OperationResourceRequirementOut:
    oid = resolver.routing_operation_id(db, payload.operation_id)
    row = OperationResourceRequirement(
        routing_operation_id=oid,
        required_resource_type=payload.required_resource_type,
        required_resource_id=payload.required_resource_id,
        required_quantity=payload.required_quantity,
        is_mandatory=payload.is_mandatory,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Operation resource requirement could not be committed: {exc.orig}")
    db.refresh(row)
    return _req_to_out(db, row)
