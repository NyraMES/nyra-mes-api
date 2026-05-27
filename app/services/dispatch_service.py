"""Dispatch service.

Workflow rule: a lot can only be dispatched when
* its work orders are all 'Completed', and
* it has at least one Passed inspection result, and
* it has no open NCRs.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, WorkflowError
from app.models.dispatch import Dispatch, DispatchLine
from app.models.production import ProductionLot
from app.models.quality import InspectionResult
from app.models.traceability import TraceabilityClosure
from app.utils.time import utcnow
from app.models.work_order import WorkOrder
from app.schemas.dispatch import (
    DispatchCreate,
    DispatchLineCreate,
    DispatchLineOut,
    DispatchOut,
)
from app.services import ncr_service, resolver
from app.utils.ids import generate_business_id


def _to_out(db: Session, row: Dispatch) -> DispatchOut:
    return DispatchOut(
        id=row.id,
        dispatch_id=row.dispatch_code,
        customer_id=resolver.customer_code(db, row.customer_id) if row.customer_id else None,
        order_id=resolver.order_code(db, row.order_id) if row.order_id else None,
        dispatch_date=row.dispatch_date,
        vehicle_number=row.vehicle_number,
        transporter_name=row.transporter_name,
        dispatch_status=row.dispatch_status,
        remarks=row.remarks,
        created_at=row.created_at,
    )


def _line_to_out(db: Session, row: DispatchLine) -> DispatchLineOut:
    return DispatchLineOut(
        id=row.id,
        dispatch_line_id=row.id,
        dispatch_id=resolver.dispatch_code(db, row.dispatch_id) if row.dispatch_id else None,
        lot_id=resolver.lot_code(db, row.lot_id) if row.lot_id else None,
        part_id=resolver.part_code(db, row.part_id) if row.part_id else None,
        dispatch_quantity=row.dispatch_quantity,
        accepted_quantity=row.accepted_quantity,
        rejected_quantity=row.rejected_quantity,
        created_at=row.created_at,
    )


def _assert_lot_dispatch_eligible(db: Session, lot_code: str) -> ProductionLot:
    lot_pk = resolver.lot_id(db, lot_code)
    lot = db.query(ProductionLot).filter(ProductionLot.id == lot_pk).first()
    if not lot:
        raise NotFoundError(f"Production lot '{lot_code}' not found")

    # all work orders completed
    incomplete = (
        db.query(WorkOrder.id)
        .filter(WorkOrder.lot_id == lot_pk)
        .filter(
            (WorkOrder.work_order_status.is_(None))
            | (WorkOrder.work_order_status != "Completed")
        )
        .count()
    )
    if incomplete > 0:
        raise WorkflowError(
            f"Lot '{lot_code}' has {incomplete} incomplete operations; cannot dispatch"
        )

    # at least one passed inspection
    passed = (
        db.query(InspectionResult.id)
        .filter(InspectionResult.lot_id == lot_pk)
        .filter(InspectionResult.inspection_status == "Passed")
        .count()
    )
    if passed == 0:
        raise WorkflowError(
            f"Lot '{lot_code}' has no passed inspection result; cannot dispatch"
        )

    if ncr_service.has_open_ncrs_for_lot(db, lot_code):
        raise WorkflowError(
            f"Lot '{lot_code}' has open NCRs; resolve them before dispatch"
        )
    return lot


def _record_traceability_closure(
    db: Session,
    *,
    lot_pk: int,
    dispatch_pk: int,
    order_pk: Optional[int] = None,
) -> None:
    """Persist closure row so traceability shows dispatch + quality outcome."""
    lot = db.query(ProductionLot).filter(ProductionLot.id == lot_pk).first()
    if not lot:
        return
    passed = (
        db.query(InspectionResult)
        .filter(
            InspectionResult.lot_id == lot_pk,
            InspectionResult.inspection_status == "Passed",
        )
        .order_by(InspectionResult.id.desc())
        .first()
    )
    db.add(
        TraceabilityClosure(
            lot_id=lot_pk,
            order_id=order_pk,
            production_order_id=lot.production_order_id,
            final_quality_status=(
                passed.inspection_status if passed else "Passed"
            ),
            dispatch_id=dispatch_pk,
            closure_status="Closed",
            closed_at=utcnow(),
        )
    )


def list_dispatches(db: Session) -> List[DispatchOut]:
    rows = db.query(Dispatch).order_by(Dispatch.id).all()
    return [_to_out(db, r) for r in rows]


def get_dispatch(db: Session, code: str) -> DispatchOut:
    row = db.query(Dispatch).filter(Dispatch.dispatch_code == code).first()
    if not row:
        raise NotFoundError(f"Dispatch '{code}' not found")
    return _to_out(db, row)


def list_lines(db: Session, dispatch_code: str) -> List[DispatchLineOut]:
    pk = resolver.dispatch_id(db, dispatch_code)
    rows = (
        db.query(DispatchLine)
        .filter(DispatchLine.dispatch_id == pk)
        .order_by(DispatchLine.id)
        .all()
    )
    return [_line_to_out(db, r) for r in rows]


def create_dispatch(
    db: Session, payload: DispatchCreate
) -> Tuple[DispatchOut, List[DispatchLineOut]]:
    # If lines come along, vet each lot now.
    if payload.lines:
        for line in payload.lines:
            _assert_lot_dispatch_eligible(db, line.lot_id)

    code = (payload.dispatch_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_dispatch,
        sequence="trn.dispatch_seq",
        fallback_table="trn.dispatch",
        fallback_column="dispatch_code",
    )
    if db.query(Dispatch).filter(Dispatch.dispatch_code == code).first():
        raise ConflictError(f"Dispatch '{code}' already exists")

    row = Dispatch(
        dispatch_code=code,
        customer_id=resolver.customer_id(db, payload.customer_id),
        order_id=resolver.order_id(db, payload.order_id) if payload.order_id else None,
        dispatch_date=payload.dispatch_date,
        vehicle_number=payload.vehicle_number,
        transporter_name=payload.transporter_name,
        dispatch_status=payload.dispatch_status or "Ready",
        remarks=payload.remarks,
    )
    db.add(row)
    db.flush()

    line_rows: List[DispatchLine] = []
    for line in payload.lines or []:
        accepted = (
            line.accepted_quantity
            if line.accepted_quantity is not None
            else line.dispatch_quantity
        )
        lot_pk = resolver.lot_id(db, line.lot_id)
        part_pk = resolver.part_id(db, line.part_id)
        line_row = DispatchLine(
            dispatch_id=row.id,
            lot_id=lot_pk,
            part_id=part_pk,
            dispatch_quantity=line.dispatch_quantity,
            accepted_quantity=accepted,
            rejected_quantity=line.rejected_quantity or 0,
        )
        db.add(line_row)
        line_rows.append(line_row)

        # Mark lot dispatched + close traceability
        lot = db.query(ProductionLot).filter(ProductionLot.id == lot_pk).first()
        if lot:
            lot.status = "Dispatched"
        _record_traceability_closure(
            db,
            lot_pk=lot_pk,
            dispatch_pk=row.id,
            order_pk=row.order_id,
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Dispatch '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    for r in line_rows:
        db.refresh(r)
    return _to_out(db, row), [_line_to_out(db, r) for r in line_rows]


def add_dispatch_line(
    db: Session, dispatch_code: str, payload: DispatchLineCreate
) -> DispatchLineOut:
    dispatch_pk = resolver.dispatch_id(db, dispatch_code)
    _assert_lot_dispatch_eligible(db, payload.lot_id)
    lot_pk = resolver.lot_id(db, payload.lot_id)
    part_pk = resolver.part_id(db, payload.part_id)
    accepted = (
        payload.accepted_quantity
        if payload.accepted_quantity is not None
        else payload.dispatch_quantity
    )
    row = DispatchLine(
        dispatch_id=dispatch_pk,
        lot_id=lot_pk,
        part_id=part_pk,
        dispatch_quantity=payload.dispatch_quantity,
        accepted_quantity=accepted,
        rejected_quantity=payload.rejected_quantity or 0,
    )
    db.add(row)

    lot = db.query(ProductionLot).filter(ProductionLot.id == lot_pk).first()
    dispatch_hdr = db.query(Dispatch).filter(Dispatch.id == dispatch_pk).first()
    if lot:
        lot.status = "Dispatched"
    _record_traceability_closure(
        db,
        lot_pk=lot_pk,
        dispatch_pk=dispatch_pk,
        order_pk=dispatch_hdr.order_id if dispatch_hdr else None,
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Dispatch line could not be committed: {exc.orig}")
    db.refresh(row)
    return _line_to_out(db, row)
