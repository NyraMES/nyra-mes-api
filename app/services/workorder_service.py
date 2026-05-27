"""Work-order service.

The frontend's "execution screen" reads through this service. Each work
order corresponds to one routing-operation on one production lot. The
``/lot/{lot_id}/execution-summary`` aggregation also lives here.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, WorkflowError
from app.models.order import CustomerOrder, CustomerOrderLine
from app.models.part import Part
from app.models.production import ProductionLot, ProductionOrder
from app.models.maintenance import MachineDowntime
from app.models.resource import Machine, WorkCenter
from app.models.routing import RoutingOperation
from app.models.schedule import ProductionSchedule
from app.models.work_order import WorkOrder, WorkOrderEvent
from app.schemas.schedule import (
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderHoldRequest,
    WorkOrderOut,
    WorkOrderStartRequest,
)
from app.services import resolver
from app.utils.ids import generate_business_id
from app.utils.time import utcnow


_DOWNTIME_RE = re.compile(r"Downtime:\s*([\d.]+)\s*min", re.I)
_MACHINE_RE = re.compile(r"Machine:\s*([^|]+)", re.I)
_OPERATOR_RE = re.compile(r"Operator:\s*([^|]+)", re.I)


def _parse_downtime_from_remarks(remarks: Optional[str]) -> Optional[Decimal]:
    if not remarks:
        return None
    m = _DOWNTIME_RE.search(remarks)
    if not m:
        return None
    try:
        return Decimal(m.group(1))
    except Exception:
        return None


def _parse_field_from_remarks(remarks: Optional[str], pattern: re.Pattern) -> Optional[str]:
    if not remarks:
        return None
    m = pattern.search(remarks)
    return m.group(1).strip() if m else None


def _execution_extras_for_work_orders(
    db: Session, wo_ids: List[int]
) -> Dict[int, Tuple[Optional[str], Optional[str], Optional[Decimal]]]:
    """Map work_order.id -> (operator_name, actual_machine_code, downtime_minutes)."""
    if not wo_ids:
        return {}
    out: Dict[int, Tuple[Optional[str], Optional[str], Optional[Decimal]]] = {
        wid: (None, None, None) for wid in wo_ids
    }

    for dt in (
        db.query(MachineDowntime)
        .filter(MachineDowntime.work_order_id.in_(wo_ids))
        .order_by(MachineDowntime.id.desc())
        .all()
    ):
        if dt.work_order_id and out[dt.work_order_id][2] is None and dt.downtime_minutes is not None:
            op, mc, _ = out[dt.work_order_id]
            out[dt.work_order_id] = (op, mc, Decimal(str(dt.downtime_minutes)))

    events = (
        db.query(WorkOrderEvent)
        .filter(WorkOrderEvent.work_order_id.in_(wo_ids))
        .order_by(WorkOrderEvent.work_order_id, WorkOrderEvent.id.desc())
        .all()
    )
    seen_started: set = set()
    seen_completed: set = set()
    for evt in events:
        wid = evt.work_order_id
        if not wid or wid not in out:
            continue
        op, mc, dt = out[wid]
        et = (evt.event_type or "").lower()
        if et == "started" and wid not in seen_started:
            seen_started.add(wid)
            if not op:
                op = _parse_field_from_remarks(evt.remarks, _OPERATOR_RE)
        if et == "completed" and wid not in seen_completed:
            seen_completed.add(wid)
            if not op:
                op = _parse_field_from_remarks(evt.remarks, _OPERATOR_RE)
            if not mc:
                mc = _parse_field_from_remarks(evt.remarks, _MACHINE_RE)
            if dt is None:
                dt = _parse_downtime_from_remarks(evt.remarks)
        out[wid] = (op, mc, dt)
    return out


def _to_out(
    db: Session,
    row: WorkOrder,
    *,
    operator_name: Optional[str] = None,
    actual_machine_id: Optional[str] = None,
    downtime_minutes: Optional[Decimal] = None,
) -> WorkOrderOut:
    extras = _execution_extras_for_work_orders(db, [row.id]).get(row.id, (None, None, None))
    op = operator_name if operator_name is not None else extras[0]
    machine = actual_machine_id if actual_machine_id is not None else extras[1]
    downtime = downtime_minutes if downtime_minutes is not None else extras[2]
    return WorkOrderOut(
        id=row.id,
        work_order_id=row.work_order_code,
        schedule_id=resolver.schedule_code(db, row.schedule_id) if row.schedule_id else None,
        lot_id=resolver.lot_code(db, row.lot_id) if row.lot_id else None,
        operation_id=resolver.operation_code(db, row.routing_operation_id) if row.routing_operation_id else None,
        work_order_status=row.work_order_status,
        released_at=row.released_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        actual_output_quantity=row.actual_output_quantity,
        scrap_quantity=row.scrap_quantity,
        rework_quantity=row.rework_quantity,
        operator_name=op,
        actual_machine_id=machine,
        downtime_minutes=downtime,
    )


def _resolve_machine_pk_for_wo(
    db: Session,
    row: WorkOrder,
    machine_code: Optional[str] = None,
) -> Optional[int]:
    code = (machine_code or "").strip()
    if code:
        try:
            return resolver.machine_id(db, code)
        except NotFoundError:
            pass
    if row.schedule_id:
        sched = (
            db.query(ProductionSchedule)
            .filter(ProductionSchedule.id == row.schedule_id)
            .first()
        )
        if sched and sched.assigned_machine_id:
            return int(sched.assigned_machine_id)
    return None


def _log_execution_downtime(
    db: Session,
    row: WorkOrder,
    payload: WorkOrderCompleteRequest,
    *,
    machine_pk: Optional[int] = None,
) -> None:
    """Persist downtime to ``trn.machine_downtime`` (works without WO column migration)."""
    if payload.downtime_minutes is None:
        return
    try:
        mins = Decimal(str(payload.downtime_minutes))
    except Exception:
        return
    if mins <= 0:
        return
    pk = machine_pk or _resolve_machine_pk_for_wo(db, row, payload.machine_id)
    if not pk:
        return
    db.add(
        MachineDowntime(
            machine_id=pk,
            work_order_id=row.id,
            downtime_reason=f"Execution {row.work_order_code}",
            downtime_start=row.started_at,
            downtime_end=row.completed_at,
            downtime_minutes=mins,
        )
    )


def _complete_remarks(payload: WorkOrderCompleteRequest) -> Optional[str]:
    parts: List[str] = []
    if payload.machine_id and str(payload.machine_id).strip():
        parts.append(f"Machine: {str(payload.machine_id).strip()}")
    if payload.downtime_minutes is not None:
        parts.append(f"Downtime: {payload.downtime_minutes} min")
    if payload.operator_name and str(payload.operator_name).strip():
        parts.append(f"Operator: {str(payload.operator_name).strip()}")
    if payload.remarks and str(payload.remarks).strip():
        parts.append(str(payload.remarks).strip())
    return " | ".join(parts) if parts else None


def list_work_orders(db: Session) -> List[WorkOrderOut]:
    rows = db.query(WorkOrder).order_by(WorkOrder.id).all()
    return [_to_out(db, r) for r in rows]


def get_work_order(db: Session, code: str) -> WorkOrderOut:
    row = db.query(WorkOrder).filter(WorkOrder.work_order_code == code).first()
    if not row:
        raise NotFoundError(f"Work order '{code}' not found")
    return _to_out(db, row)


def _next_code(db: Session) -> str:
    return generate_business_id(
        db,
        prefix=settings.id_prefix_work_order,
        sequence="trn.work_order_seq",
        fallback_table="trn.work_order",
        fallback_column="work_order_code",
    )


def create_work_order(db: Session, payload: WorkOrderCreate) -> WorkOrderOut:
    code = (payload.work_order_id or "").strip() or _next_code(db)
    if db.query(WorkOrder).filter(WorkOrder.work_order_code == code).first():
        raise ConflictError(f"Work order '{code}' already exists")

    row = WorkOrder(
        work_order_code=code,
        schedule_id=resolver.schedule_id(db, payload.schedule_id) if payload.schedule_id else None,
        lot_id=resolver.lot_id(db, payload.lot_id),
        routing_operation_id=(
            resolver.routing_operation_id(db, payload.operation_id)
            if payload.operation_id
            else None
        ),
        work_order_status=payload.work_order_status or "Released",
        released_at=utcnow() if (payload.work_order_status or "Released") == "Released" else None,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Work order '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    _emit_event(db, row.id, "Released")
    return _to_out(db, row)


def start_work_order(
    db: Session, code: str, payload: Optional[WorkOrderStartRequest] = None
) -> WorkOrderOut:
    row = db.query(WorkOrder).filter(WorkOrder.work_order_code == code).first()
    if not row:
        raise NotFoundError(f"Work order '{code}' not found")
    status = (row.work_order_status or "").lower()
    if status == "completed":
        raise WorkflowError("Cannot start a completed work order")
    if status not in ("released", "ready"):
        raise WorkflowError(
            f"Work order must be Ready to start (current: {row.work_order_status})"
        )
    if row.started_at:
        raise WorkflowError("Work order already started")
    _assert_prior_operations_complete(db, row)
    row.started_at = utcnow()
    row.work_order_status = "InProgress"
    operator = (payload.operator_name if payload else None) or ""
    remark = f"Operator: {operator.strip()}" if operator.strip() else None
    _append_work_order_event(db, row.id, "Started", remark)
    db.commit()
    db.refresh(row)
    return _to_out(
        db,
        row,
        operator_name=operator.strip() or None,
    )


def hold_work_order(
    db: Session, code: str, payload: WorkOrderHoldRequest
) -> WorkOrderOut:
    row = db.query(WorkOrder).filter(WorkOrder.work_order_code == code).first()
    if not row:
        raise NotFoundError(f"Work order '{code}' not found")
    status = (row.work_order_status or "").lower()
    if status == "completed":
        raise WorkflowError("Cannot hold a completed work order")
    if status == "onhold":
        raise WorkflowError("Work order is already on hold")
    if status not in ("released", "ready", "inprogress", "in progress"):
        raise WorkflowError(f"Cannot hold work order in status '{row.work_order_status}'")
    reason = (payload.reason or "").strip()
    if not reason:
        raise WorkflowError("Hold reason is required")
    row.work_order_status = "OnHold"
    _append_work_order_event(db, row.id, "OnHold", reason)
    db.commit()
    db.refresh(row)
    return _to_out(db, row)


def resume_work_order(db: Session, code: str) -> WorkOrderOut:
    row = db.query(WorkOrder).filter(WorkOrder.work_order_code == code).first()
    if not row:
        raise NotFoundError(f"Work order '{code}' not found")
    if (row.work_order_status or "").lower() != "onhold":
        raise WorkflowError("Work order is not on hold")
    row.work_order_status = "InProgress" if row.started_at else "Released"
    _append_work_order_event(db, row.id, "Resumed")
    db.commit()
    db.refresh(row)
    return _to_out(db, row)


def complete_work_order(
    db: Session, code: str, payload: WorkOrderCompleteRequest
) -> WorkOrderOut:
    row = db.query(WorkOrder).filter(WorkOrder.work_order_code == code).first()
    if not row:
        raise NotFoundError(f"Work order '{code}' not found")
    if not row.started_at:
        raise WorkflowError("Work order must be started before completion")
    if row.completed_at:
        raise WorkflowError("Work order already completed")
    row.completed_at = utcnow()
    row.work_order_status = "Completed"
    row.actual_output_quantity = payload.actual_output_quantity
    row.scrap_quantity = payload.scrap_quantity
    row.rework_quantity = payload.rework_quantity
    machine_code = (payload.machine_id or "").strip() if payload.machine_id else ""
    machine_pk: Optional[int] = None
    if machine_code:
        machine_pk = resolver.machine_id(db, machine_code)
    remarks = _complete_remarks(payload)
    db.flush()
    _log_execution_downtime(db, row, payload, machine_pk=machine_pk)
    _append_work_order_event(db, row.id, "Completed", remarks)
    db.commit()
    db.refresh(row)
    downtime_val = None
    if payload.downtime_minutes is not None:
        try:
            downtime_val = Decimal(str(payload.downtime_minutes))
        except Exception:
            downtime_val = None
    return _to_out(
        db,
        row,
        operator_name=(str(payload.operator_name).strip() if payload.operator_name else None),
        actual_machine_id=machine_code or None,
        downtime_minutes=downtime_val,
    )


def _append_work_order_event(
    db: Session,
    work_order_pk: int,
    event_type: str,
    remarks: Optional[str] = None,
) -> None:
    """Append event in the current transaction (no extra commit)."""
    db.add(
        WorkOrderEvent(
            work_order_id=work_order_pk,
            event_type=event_type,
            event_time=utcnow(),
            remarks=remarks,
        )
    )


def _emit_event(
    db: Session,
    work_order_pk: int,
    event_type: str,
    remarks: Optional[str] = None,
) -> None:
    _append_work_order_event(db, work_order_pk, event_type, remarks)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def _assert_prior_operations_complete(db: Session, row: WorkOrder) -> None:
    """Routing is sequential — block starting op N until op N-1 is completed."""
    if not row.lot_id or not row.routing_operation_id:
        return
    current = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.id == row.routing_operation_id)
        .first()
    )
    if not current or not current.routing_id:
        return
    prior_ops = (
        db.query(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == current.routing_id,
            RoutingOperation.operation_sequence < current.operation_sequence,
        )
        .all()
    )
    for pop in prior_ops:
        prior_wo = (
            db.query(WorkOrder)
            .filter(
                WorkOrder.lot_id == row.lot_id,
                WorkOrder.routing_operation_id == pop.id,
            )
            .first()
        )
        if prior_wo and (prior_wo.work_order_status or "").lower() != "completed":
            raise WorkflowError(
                f"Complete step {pop.operation_sequence} ({pop.operation_name}) before starting this operation",
                details={
                    "blocking_operation": pop.operation_code,
                    "blocking_work_order": prior_wo.work_order_code,
                },
            )


def _latest_hold_reason(db: Session, work_order_pk: int) -> Optional[str]:
    evt = (
        db.query(WorkOrderEvent)
        .filter(
            WorkOrderEvent.work_order_id == work_order_pk,
            WorkOrderEvent.event_type == "OnHold",
        )
        .order_by(WorkOrderEvent.id.desc())
        .first()
    )
    return evt.remarks if evt else None


def sync_lot_for_execution(db: Session, lot_code: str) -> Dict[str, int]:
    """Ensure work orders exist so Execution can run after Scheduling.

    1. For each ``production_schedule`` on the lot, create or link a
       ``work_order`` (fixes lots scheduled before auto-WO creation).
    2. Materialise any remaining routing operations via ``generate_lot_route``
       (idempotent — skips ops that already have a work order).
    """
    from app.services import routing_service

    lot_pk = resolver.lot_id(db, lot_code)
    created_from_schedule = 0
    linked = 0

    schedules = (
        db.query(ProductionSchedule)
        .filter(ProductionSchedule.lot_id == lot_pk)
        .order_by(ProductionSchedule.id)
        .all()
    )

    existing_wos = (
        db.query(WorkOrder)
        .filter(WorkOrder.lot_id == lot_pk)
        .all()
    )
    wo_by_routing_op = {
        w.routing_operation_id: w
        for w in existing_wos
        if w.routing_operation_id is not None
    }

    for sched in schedules:
        if not sched.routing_operation_id:
            continue
        wo = wo_by_routing_op.get(sched.routing_operation_id)
        if wo:
            if wo.schedule_id != sched.id:
                wo.schedule_id = sched.id
                linked += 1
        else:
            wo_code = generate_business_id(
                db,
                prefix=settings.id_prefix_work_order,
                sequence="trn.work_order_seq",
                fallback_table="trn.work_order",
                fallback_column="work_order_code",
            )
            db.add(
                WorkOrder(
                    work_order_code=wo_code,
                    schedule_id=sched.id,
                    lot_id=lot_pk,
                    routing_operation_id=sched.routing_operation_id,
                    work_order_status="Released",
                    released_at=utcnow(),
                )
            )
            created_from_schedule += 1

    if created_from_schedule or linked:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    total_wo = (
        db.query(WorkOrder).filter(WorkOrder.lot_id == lot_pk).count()
    )
    # Only materialise routing WOs when none exist yet (skip on every refresh).
    if total_wo == 0:
        try:
            routing_service.generate_lot_route(db, lot_code)[0]
        except WorkflowError:
            pass  # no routing on part yet — schedules may still have created WOs
        total_wo = (
            db.query(WorkOrder).filter(WorkOrder.lot_id == lot_pk).count()
        )
    return {
        "schedules_found": len(schedules),
        "work_orders_created_from_schedules": created_from_schedule,
        "schedules_linked": linked,
        "work_orders_total": total_wo,
    }


def _ui_status(work_order_status: Optional[str]) -> str:
    """Map DB work-order status to labels the execution UI understands."""
    s = (work_order_status or "").strip().lower()
    if s == "released":
        return "Ready"
    if s in ("inprogress", "in progress"):
        return "In Progress"
    if s == "completed":
        return "Completed"
    if s == "onhold":
        return "On Hold"
    return work_order_status or "Pending"


def _batch_hold_reasons(db: Session, work_order_pks: List[int]) -> Dict[int, str]:
    if not work_order_pks:
        return {}
    events = (
        db.query(WorkOrderEvent)
        .filter(
            WorkOrderEvent.work_order_id.in_(work_order_pks),
            WorkOrderEvent.event_type == "OnHold",
        )
        .order_by(WorkOrderEvent.work_order_id, WorkOrderEvent.id.desc())
        .all()
    )
    out: Dict[int, str] = {}
    for evt in events:
        if evt.work_order_id and evt.work_order_id not in out and evt.remarks:
            out[evt.work_order_id] = evt.remarks
    return out


def _can_start_in_memory(
    wo: WorkOrder,
    rop: Optional[RoutingOperation],
    rows: List[tuple],
    completed_op_ids: set,
) -> bool:
    if (wo.work_order_status or "").lower() != "released" or wo.started_at:
        return False
    if not rop or not rop.routing_id:
        return True
    for _wo, prior_rop in rows:
        if (
            prior_rop
            and prior_rop.routing_id == rop.routing_id
            and prior_rop.operation_sequence is not None
            and rop.operation_sequence is not None
            and prior_rop.operation_sequence < rop.operation_sequence
            and prior_rop.id not in completed_op_ids
        ):
            return False
    return True


def lot_execution_summary(
    db: Session, lot_code: str, *, sync: bool = False
) -> Dict[str, Any]:
    """Aggregate work-order state for a lot, used by the execution screen.

    Pass ``sync=true`` on first load to link schedules to work orders.
    Default ``sync=false`` keeps start/complete refreshes fast on remote DBs.
    """

    sync_meta = (
        sync_lot_for_execution(db, lot_code)
        if sync
        else {"sync_skipped": True, "schedules_found": 0}
    )

    lot_pk = resolver.lot_id(db, lot_code)
    lot_row = db.query(ProductionLot).filter(ProductionLot.id == lot_pk).first()
    part_code = None
    part_name = None
    production_order_code = None
    customer_order_code = None
    customer_code = None
    if lot_row and lot_row.production_order_id:
        po = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.id == lot_row.production_order_id)
            .first()
        )
        if po:
            production_order_code = resolver.production_order_code(db, po.id)
            if po.order_line_id:
                line = (
                    db.query(CustomerOrderLine)
                    .filter(CustomerOrderLine.id == po.order_line_id)
                    .first()
                )
                if line:
                    if line.order_id:
                        customer_order_code = resolver.order_code(db, line.order_id)
                        order_row = (
                            db.query(CustomerOrder)
                            .filter(CustomerOrder.id == line.order_id)
                            .first()
                        )
                        if order_row and order_row.customer_id:
                            customer_code = resolver.customer_code(
                                db, order_row.customer_id
                            )
                    if line.part_id:
                        p = db.query(Part).filter(Part.id == line.part_id).first()
                        if p:
                            part_code = p.part_code
                            part_name = p.part_name

    rows = (
        db.query(WorkOrder, RoutingOperation)
        .outerjoin(RoutingOperation, WorkOrder.routing_operation_id == RoutingOperation.id)
        .filter(WorkOrder.lot_id == lot_pk)
        .order_by(RoutingOperation.operation_sequence.nullslast(), WorkOrder.id)
        .all()
    )

    sched_ids = {wo.schedule_id for wo, _ in rows if wo.schedule_id}
    schedule_by_id: Dict[int, ProductionSchedule] = {}
    if sched_ids:
        for sched in (
            db.query(ProductionSchedule)
            .filter(ProductionSchedule.id.in_(sched_ids))
            .all()
        ):
            schedule_by_id[sched.id] = sched

    machine_pks = {
        s.assigned_machine_id
        for s in schedule_by_id.values()
        if s.assigned_machine_id
    }
    wc_pks = {
        s.assigned_work_center_id
        for s in schedule_by_id.values()
        if s.assigned_work_center_id
    }
    machine_codes: Dict[int, str] = {}
    if machine_pks:
        for mid, code in (
            db.query(Machine.id, Machine.machine_code)
            .filter(Machine.id.in_(machine_pks))
            .all()
        ):
            machine_codes[mid] = code
    wc_codes: Dict[int, str] = {}
    if wc_pks:
        for wid, code in (
            db.query(WorkCenter.id, WorkCenter.work_center_code)
            .filter(WorkCenter.id.in_(wc_pks))
            .all()
        ):
            wc_codes[wid] = code

    schedule_codes: Dict[int, str] = {}
    if sched_ids:
        for sid, code in (
            db.query(ProductionSchedule.id, ProductionSchedule.schedule_code)
            .filter(ProductionSchedule.id.in_(sched_ids))
            .all()
        ):
            if code:
                schedule_codes[sid] = code

    wo_pks = [wo.id for wo, _ in rows]
    hold_by_wo = _batch_hold_reasons(db, wo_pks)
    exec_extras = _execution_extras_for_work_orders(db, wo_pks)
    completed_op_ids = {
        rop.id
        for wo, rop in rows
        if rop and (wo.work_order_status or "").lower() == "completed"
    }

    operations = []
    for wo, rop in rows:
        op_code = (
            rop.operation_code
            if rop
            else resolver.operation_code(db, wo.routing_operation_id)
        )
        op_name = rop.operation_name if rop else None
        seq = rop.operation_sequence if rop else None
        ui = _ui_status(wo.work_order_status)

        sched_machine = None
        sched_wc = None
        sched = schedule_by_id.get(wo.schedule_id) if wo.schedule_id else None
        if sched:
            if sched.assigned_machine_id:
                sched_machine = machine_codes.get(sched.assigned_machine_id)
            if sched.assigned_work_center_id:
                sched_wc = wc_codes.get(sched.assigned_work_center_id)

        can_start = _can_start_in_memory(wo, rop, rows, completed_op_ids)
        op_name_extra, actual_machine_code, downtime_mins = exec_extras.get(
            wo.id, (None, None, None)
        )
        display_machine = actual_machine_code or sched_machine

        operations.append(
            {
                "work_order_id": wo.work_order_code,
                "lot_operation_id": wo.work_order_code,
                "operation_id": op_code,
                "operation_code": op_code,
                "operation_name": op_name or op_code or "Operation",
                "seq": seq,
                "status": ui,
                "work_order_status": wo.work_order_status,
                "schedule_id": schedule_codes.get(wo.schedule_id) if wo.schedule_id else None,
                "assigned_machine_id": sched_machine,
                "assigned_work_center_id": sched_wc,
                "hold_reason": hold_by_wo.get(wo.id),
                "can_start": can_start,
                "actual_output_quantity": wo.actual_output_quantity,
                "scrap_quantity": wo.scrap_quantity,
                "rework_quantity": wo.rework_quantity,
                "operator_name": op_name_extra,
                "actual_machine_id": display_machine,
                "downtime_minutes": (
                    float(downtime_mins) if downtime_mins is not None else None
                ),
                "released_at": wo.released_at,
                "started_at": wo.started_at,
                "completed_at": wo.completed_at,
            }
        )

    operations.sort(
        key=lambda op: (
            op["seq"] is None,
            op["seq"] if op["seq"] is not None else 999999,
            op["work_order_id"],
        )
    )

    total = len(rows)
    completed = sum(
        1 for wo, _ in rows if (wo.work_order_status or "").lower() == "completed"
    )
    in_progress = sum(
        1 for wo, _ in rows if (wo.work_order_status or "").lower() == "inprogress"
    )
    ready_count = sum(1 for op in operations if op["status"] == "Ready")
    on_hold_count = sum(1 for op in operations if op["status"] == "On Hold")
    schedules_count = sync_meta.get("schedules_found", 0)

    return {
        "lot_id": lot_code,
        "lot_status": lot_row.status if lot_row else None,
        "lot_quantity": lot_row.lot_quantity if lot_row else None,
        "production_order_id": production_order_code,
        "customer_order_id": customer_order_code,
        "customer_id": customer_code,
        "part_id": part_code,
        "part_name": part_name,
        "operations_total": total,
        "operations_completed": completed,
        "operations_in_progress": in_progress,
        "operations_ready": ready_count,
        "operations_on_hold": on_hold_count,
        "schedules_count": schedules_count,
        "execution_ready": total > 0 and (ready_count > 0 or in_progress > 0 or on_hold_count > 0),
        "sync": sync_meta,
        "operations": operations,
    }
