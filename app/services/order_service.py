"""Customer-order service.

Translates between the wire contract (string ``order_id`` / ``customer_id``
= business codes) and the DB FK ids (bigint).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.order import CustomerOrder, CustomerOrderLine
from app.schemas.order import (
    OrderCreate,
    OrderLineCreate,
    OrderLineOut,
    OrderOut,
)
from app.services import resolver
from app.utils.ids import generate_business_id


def _order_to_out(db: Session, row: CustomerOrder) -> OrderOut:
    return OrderOut(
        id=row.id,
        order_id=row.order_code,
        customer_id=resolver.customer_code(db, row.customer_id) if row.customer_id else None,
        order_date=row.order_date,
        delivery_date=row.delivery_date,
        status=row.status,
        created_at=row.created_at,
    )


def _line_to_out(db: Session, row: CustomerOrderLine) -> OrderLineOut:
    return OrderLineOut(
        id=row.id,
        order_line_id=row.order_line_code,
        order_id=resolver.order_code(db, row.order_id) if row.order_id else "",
        part_id=resolver.part_code(db, row.part_id) if row.part_id else None,
        quantity=row.quantity,
        status=row.status,
        created_at=row.created_at,
    )


def _next_order_line_code(db: Session, provided: Optional[str] = None) -> str:
    """Generate (or accept) the ``ORDLxxxxx`` business code for a line."""
    code = (provided or "").strip()
    if code:
        if (
            db.query(CustomerOrderLine)
            .filter(CustomerOrderLine.order_line_code == code)
            .first()
        ):
            raise ConflictError(f"Order line '{code}' already exists")
        return code
    return generate_business_id(
        db,
        prefix=settings.id_prefix_order_line,
        sequence="trn.order_line_seq",
        fallback_table="trn.customer_order_line",
        fallback_column="order_line_code",
    )


def list_orders(db: Session) -> List[OrderOut]:
    rows = db.query(CustomerOrder).order_by(CustomerOrder.id).all()
    return [_order_to_out(db, r) for r in rows]


def get_order(db: Session, code: str) -> OrderOut:
    row = db.query(CustomerOrder).filter(CustomerOrder.order_code == code).first()
    if not row:
        raise NotFoundError(f"Order '{code}' not found")
    return _order_to_out(db, row)


def list_all_lines(db: Session) -> List[OrderLineOut]:
    """All order lines in one query (avoids N+1 HTTP calls from the UI)."""
    rows = (
        db.query(CustomerOrderLine)
        .order_by(CustomerOrderLine.id.desc())
        .all()
    )
    return [_line_to_out(db, r) for r in rows]


def list_lines(db: Session, order_code: str) -> List[OrderLineOut]:
    oid = resolver.order_id(db, order_code)
    rows = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == oid)
        .order_by(CustomerOrderLine.id)
        .all()
    )
    return [_line_to_out(db, r) for r in rows]


def create_order(db: Session, payload: OrderCreate) -> Tuple[OrderOut, List[OrderLineOut]]:
    code = (payload.order_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_order,
        sequence="trn.order_seq",
        fallback_table="trn.customer_order",
        fallback_column="order_code",
    )
    if db.query(CustomerOrder).filter(CustomerOrder.order_code == code).first():
        raise ConflictError(f"Order '{code}' already exists")

    customer_pk = resolver.customer_id(db, payload.customer_id)

    order = CustomerOrder(
        order_code=code,
        customer_id=customer_pk,
        order_date=payload.order_date,
        delivery_date=payload.delivery_date,
        status=payload.status or "Created",
    )
    db.add(order)
    db.flush()  # need order.id for line FKs

    created_lines: List[CustomerOrderLine] = []
    for line in payload.lines or []:
        part_pk = resolver.part_id(db, line.part_id)
        line_row = CustomerOrderLine(
            order_line_code=_next_order_line_code(db, line.order_line_id),
            order_id=order.id,
            part_id=part_pk,
            quantity=line.quantity,
            status=line.status or "Planned",
        )
        db.add(line_row)
        created_lines.append(line_row)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Order '{code}' could not be committed: {exc.orig}")
    db.refresh(order)
    for ln in created_lines:
        db.refresh(ln)

    return _order_to_out(db, order), [_line_to_out(db, ln) for ln in created_lines]


def add_line(db: Session, order_code: str, payload: OrderLineCreate) -> OrderLineOut:
    oid = resolver.order_id(db, order_code)
    part_pk = resolver.part_id(db, payload.part_id)
    line = CustomerOrderLine(
        order_line_code=_next_order_line_code(db, payload.order_line_id),
        order_id=oid,
        part_id=part_pk,
        quantity=payload.quantity,
        status=payload.status or "Planned",
    )
    db.add(line)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Order line could not be committed: {exc.orig}")
    db.refresh(line)
    return _line_to_out(db, line)


def resolve_line_for_production(
    db: Session, order_line_id: int
) -> Tuple[CustomerOrderLine, Optional[str], Optional[str]]:
    """Used by production_service to render order/part codes when listing
    production orders. Returns (line, order_code, part_code)."""

    line = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.id == order_line_id)
        .first()
    )
    if not line:
        raise NotFoundError(f"Order line '{order_line_id}' not found")
    o_code = resolver.order_code(db, line.order_id) if line.order_id else None
    p_code = resolver.part_code(db, line.part_id) if line.part_id else None
    return line, o_code, p_code
