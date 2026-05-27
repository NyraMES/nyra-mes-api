"""Production-order and production-lot service.

Workflow rules enforced here
----------------------------
* Lots can only be created for a known ``production_order_code``.
* If split lots are provided, their summed quantities must equal the
  parent production order's ``planned_quantity``.
* All FK columns hold bigint surrogate IDs; codes are translated at the
  boundary using ``app.services.resolver``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    InternalError,
    NotFoundError,
    ValidationError,
    WorkflowError,
)
from app.models.order import CustomerOrderLine
from app.models.production import ProductionLot, ProductionOrder
from app.schemas.production import (
    LotSplitRequest,
    ProductionLotCreate,
    ProductionLotOut,
    ProductionOrderCreate,
    ProductionOrderOut,
    ProductionOrderWithLotsCreate,
)
from app.services import resolver
from app.utils.ids import generate_business_id


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def _po_to_out(db: Session, row: ProductionOrder) -> ProductionOrderOut:
    return ProductionOrderOut(
        id=row.id,
        production_order_id=row.production_order_code,
        order_line_id=(
            resolver.order_line_code(db, row.order_line_id)
            if row.order_line_id
            else None
        ),
        planned_quantity=row.planned_quantity,
        planned_start_date=row.planned_start_date,
        planned_end_date=row.planned_end_date,
        status=row.status,
        created_at=row.created_at,
    )


def _lot_to_out(db: Session, row: ProductionLot) -> ProductionLotOut:
    return ProductionLotOut(
        id=row.id,
        lot_id=row.lot_code,
        production_order_id=(
            resolver.production_order_code(db, row.production_order_id)
            if row.production_order_id
            else None
        ),
        lot_quantity=row.lot_quantity,
        status=row.status,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Production orders
# ---------------------------------------------------------------------------

def list_production_orders(db: Session) -> List[ProductionOrderOut]:
    rows = db.query(ProductionOrder).order_by(ProductionOrder.id).all()
    return [_po_to_out(db, r) for r in rows]


def get_production_order(db: Session, code: str) -> ProductionOrderOut:
    row = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.production_order_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Production order '{code}' not found")
    return _po_to_out(db, row)


def _next_production_order_code(db: Session) -> str:
    return generate_business_id(
        db,
        prefix=settings.id_prefix_production_order,
        sequence="trn.production_order_seq",
        fallback_table="trn.production_order",
        fallback_column="production_order_code",
    )


def _validate_planned_quantity_matches_line(
    db: Session, order_line_pk: int, planned_quantity: Decimal
) -> None:
    """Production order quantity must match the upstream order line quantity."""
    line = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.id == order_line_pk)
        .first()
    )
    if not line:
        raise NotFoundError("Order line not found for production order")
    line_qty = Decimal(str(line.quantity or 0))
    planned = Decimal(str(planned_quantity))
    if planned <= 0:
        raise ValidationError(
            "Planned quantity must be greater than zero",
            details={"planned_quantity": str(planned)},
        )
    if planned != line_qty:
        raise ValidationError(
            "Production order planned quantity must equal order line quantity",
            details={
                "order_line_quantity": str(line_qty),
                "planned_quantity": str(planned),
            },
        )


def _next_lot_code(db: Session, production_order_code: str) -> str:
    """Lot codes include the parent production order, e.g. ``PROD00001-LOT00002``."""
    composite_prefix = f"{production_order_code}-{settings.id_prefix_lot}"
    return generate_business_id(
        db,
        prefix=composite_prefix,
        sequence="trn.lot_seq",
        fallback_table="trn.production_lot",
        fallback_column="lot_code",
    )


def create_production_order(
    db: Session, payload: ProductionOrderCreate
) -> ProductionOrderOut:
    order_line_pk = resolver.order_line_id(db, payload.order_line_id)
    _validate_planned_quantity_matches_line(
        db, order_line_pk, Decimal(str(payload.planned_quantity))
    )

    code = (payload.production_order_id or "").strip() or _next_production_order_code(db)
    if (
        db.query(ProductionOrder)
        .filter(ProductionOrder.production_order_code == code)
        .first()
    ):
        raise ConflictError(f"Production order '{code}' already exists")

    row = ProductionOrder(
        production_order_code=code,
        order_line_id=order_line_pk,
        planned_quantity=payload.planned_quantity,
        planned_start_date=payload.planned_start_date,
        planned_end_date=payload.planned_end_date,
        status=payload.status or "Planned",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Production order '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _po_to_out(db, row)


def create_production_order_with_lots(
    db: Session, payload: ProductionOrderWithLotsCreate
) -> Tuple[ProductionOrderOut, List[ProductionLotOut]]:
    if not payload.lots:
        raise ValidationError(
            "At least one lot is required",
            details={"hint": "Pass 'lots': [...] in the request body"},
        )

    total_lot_qty = sum((Decimal(str(l.lot_quantity)) for l in payload.lots), Decimal(0))
    if total_lot_qty != Decimal(str(payload.planned_quantity)):
        raise ValidationError(
            "Sum of lot quantities must equal production order planned quantity",
            details={
                "planned_quantity": str(payload.planned_quantity),
                "lots_total": str(total_lot_qty),
            },
        )

    order_line_pk = resolver.order_line_id(db, payload.order_line_id)
    _validate_planned_quantity_matches_line(
        db, order_line_pk, Decimal(str(payload.planned_quantity))
    )

    po_code = (payload.production_order_id or "").strip() or _next_production_order_code(db)
    if (
        db.query(ProductionOrder)
        .filter(ProductionOrder.production_order_code == po_code)
        .first()
    ):
        raise ConflictError(f"Production order '{po_code}' already exists")

    po = ProductionOrder(
        production_order_code=po_code,
        order_line_id=order_line_pk,
        planned_quantity=payload.planned_quantity,
        planned_start_date=payload.planned_start_date,
        planned_end_date=payload.planned_end_date,
        status=payload.status or "Planned",
    )
    db.add(po)
    db.flush()

    lot_rows: List[ProductionLot] = []
    try:
        for lot in payload.lots:
            lot_code = (lot.lot_id or "").strip() or _next_lot_code(db, po_code)
            row = ProductionLot(
                lot_code=lot_code,
                production_order_id=po.id,
                lot_quantity=lot.lot_quantity,
                status=lot.status or "Created",
            )
            db.add(row)
            lot_rows.append(row)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Production order '{po_code}' could not be committed: {exc.orig}"
        )
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        raise InternalError(f"Unexpected error creating production order: {exc}")

    db.refresh(po)
    for r in lot_rows:
        db.refresh(r)
    return _po_to_out(db, po), [_lot_to_out(db, r) for r in lot_rows]


def split_lots(
    db: Session, production_order_code: str, payload: LotSplitRequest
) -> Tuple[ProductionOrderOut, List[ProductionLotOut]]:
    po = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.production_order_code == production_order_code)
        .first()
    )
    if not po:
        raise NotFoundError(f"Production order '{production_order_code}' not found")

    new_qty = sum((Decimal(str(l.lot_quantity)) for l in payload.lots), Decimal(0))

    existing_qty = (
        db.query(ProductionLot.lot_quantity)
        .filter(ProductionLot.production_order_id == po.id)
        .all()
    )
    existing_total = sum(
        (Decimal(str(q[0])) for q in existing_qty if q[0] is not None),
        Decimal(0),
    )
    planned = Decimal(str(po.planned_quantity or 0))
    if existing_total > 0 or len(existing_qty) > 0:
        raise WorkflowError(
            "This production order is already split into lots. Lot split cannot be performed again."
        )
    if new_qty != planned:
        raise ValidationError(
            "Lot split must allocate the full planned production quantity in one operation",
            details={
                "planned_quantity": str(planned),
                "split_total": str(new_qty),
            },
        )

    for i, lot in enumerate(payload.lots, start=1):
        lot_qty = Decimal(str(lot.lot_quantity or 0))
        if lot_qty <= 0:
            raise ValidationError(
                f"Lot {i} quantity must be greater than zero",
                details={"lot_index": i, "lot_quantity": str(lot.lot_quantity)},
            )

    rows: List[ProductionLot] = []
    for lot in payload.lots:
        code = (lot.lot_id or "").strip() or _next_lot_code(db, production_order_code)
        row = ProductionLot(
            lot_code=code,
            production_order_id=po.id,
            lot_quantity=lot.lot_quantity,
            status=lot.status or "Created",
        )
        db.add(row)
        rows.append(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Lot split could not be committed: {exc.orig}")
    for r in rows:
        db.refresh(r)
    return _po_to_out(db, po), [_lot_to_out(db, r) for r in rows]


# ---------------------------------------------------------------------------
# Lots
# ---------------------------------------------------------------------------

def list_lots_for_order(db: Session, production_order_code: str) -> List[ProductionLotOut]:
    pid = resolver.production_order_id(db, production_order_code)
    rows = (
        db.query(ProductionLot)
        .filter(ProductionLot.production_order_id == pid)
        .order_by(ProductionLot.id)
        .all()
    )
    return [_lot_to_out(db, r) for r in rows]


def list_all_lots(db: Session) -> List[ProductionLotOut]:
    """Cross-PO listing of every lot (newest first)."""
    rows = (
        db.query(ProductionLot)
        .order_by(ProductionLot.created_at.desc().nullslast(), ProductionLot.id)
        .all()
    )
    return [_lot_to_out(db, r) for r in rows]


def get_lot(db: Session, code: str) -> ProductionLotOut:
    row = db.query(ProductionLot).filter(ProductionLot.lot_code == code).first()
    if not row:
        raise NotFoundError(f"Production lot '{code}' not found")
    return _lot_to_out(db, row)


def create_lot(db: Session, payload: ProductionLotCreate) -> ProductionLotOut:
    if not payload.production_order_id:
        raise ValidationError("production_order_id is required for a standalone lot")
    pid = resolver.production_order_id(db, payload.production_order_id)
    existing_count = (
        db.query(ProductionLot).filter(ProductionLot.production_order_id == pid).count()
    )
    if existing_count > 0:
        raise WorkflowError(
            "Lots already exist for this production order. Use the lot split workflow once."
        )
    po_code = resolver.production_order_code(db, pid) or ""
    code = (payload.lot_id or "").strip() or _next_lot_code(db, po_code)

    if db.query(ProductionLot).filter(ProductionLot.lot_code == code).first():
        raise ConflictError(f"Production lot '{code}' already exists")

    row = ProductionLot(
        lot_code=code,
        production_order_id=pid,
        lot_quantity=payload.lot_quantity,
        status=payload.status or "Created",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Production lot '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _lot_to_out(db, row)
