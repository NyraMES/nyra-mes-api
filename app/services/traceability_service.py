"""Lot-traceability service.

Returns a structured genealogy graph suitable for RDF / SPARQL export
(see ``app.core.ontology``). The DB also has a pre-built view
``trn.v_lot_traceability`` which we use as a fast path; if it is missing
we assemble the same picture by traversing the FKs.
"""

from __future__ import annotations

from typing import List

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.dispatch import Dispatch, DispatchLine
from app.models.order import CustomerOrder, CustomerOrderLine
from app.models.production import ProductionLot, ProductionOrder
from app.models.traceability import TraceabilityClosure
from app.schemas.traceability import (
    TraceabilityEdge,
    TraceabilityNode,
    TraceabilityResponse,
)
from app.services import resolver


def get_traceability(db: Session, lot_code: str) -> TraceabilityResponse:
    fast = _from_view(db, lot_code)
    if fast is not None:
        return fast
    return _from_fk_traversal(db, lot_code)


def _from_view(db: Session, lot_code: str):
    try:
        row = db.execute(
            text(
                """
                SELECT lot_id, lot_code, production_order_code, order_code,
                       customer_code, part_code, lot_quantity, status,
                       dispatch_code, final_quality_status, closed_at
                  FROM trn.v_lot_traceability
                 WHERE lot_code = :lot_code
                 LIMIT 1
                """
            ),
            {"lot_code": lot_code},
        ).first()
    except SQLAlchemyError:
        db.rollback()
        return None
    if not row:
        return None
    (
        _lot_pk,
        lot_code_,
        po_code,
        order_code,
        customer_code,
        part_code,
        lot_qty,
        status,
        dispatch_code,
        final_quality,
        closed_at,
    ) = row

    nodes, edges = _build_graph(
        lot=lot_code_,
        po=po_code,
        order=order_code,
        customer=customer_code,
        part=part_code,
        dispatch=dispatch_code,
    )
    return TraceabilityResponse(
        lot_id=lot_code_,
        customer_id=customer_code,
        order_id=order_code,
        production_order_id=po_code,
        part_id=part_code,
        lot_quantity=lot_qty,
        status=status,
        dispatch_id=dispatch_code,
        final_quality_status=final_quality,
        closed_at=closed_at,
        nodes=nodes,
        edges=edges,
    )


def _from_fk_traversal(db: Session, lot_code: str) -> TraceabilityResponse:
    lot = (
        db.query(ProductionLot)
        .filter(ProductionLot.lot_code == lot_code)
        .first()
    )
    if not lot:
        raise NotFoundError(f"Production lot '{lot_code}' not found")

    po_code = None
    order_code = None
    customer_code = None
    part_code = None
    if lot.production_order_id:
        po = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.id == lot.production_order_id)
            .first()
        )
        if po:
            po_code = po.production_order_code
            if po.order_line_id:
                line = (
                    db.query(CustomerOrderLine)
                    .filter(CustomerOrderLine.id == po.order_line_id)
                    .first()
                )
                if line:
                    if line.part_id:
                        part_code = resolver.part_code(db, line.part_id)
                    if line.order_id:
                        co = (
                            db.query(CustomerOrder)
                            .filter(CustomerOrder.id == line.order_id)
                            .first()
                        )
                        if co:
                            order_code = co.order_code
                            if co.customer_id:
                                customer_code = resolver.customer_code(
                                    db, co.customer_id
                                )

    dispatch_code = None
    dispatch_row = (
        db.query(Dispatch)
        .join(DispatchLine, DispatchLine.dispatch_id == Dispatch.id)
        .filter(DispatchLine.lot_id == lot.id)
        .first()
    )
    if dispatch_row:
        dispatch_code = dispatch_row.dispatch_code

    closure = (
        db.query(TraceabilityClosure)
        .filter(TraceabilityClosure.lot_id == lot.id)
        .order_by(TraceabilityClosure.id.desc())
        .first()
    )

    nodes, edges = _build_graph(
        lot=lot_code,
        po=po_code,
        order=order_code,
        customer=customer_code,
        part=part_code,
        dispatch=dispatch_code,
    )

    return TraceabilityResponse(
        lot_id=lot_code,
        customer_id=customer_code,
        order_id=order_code,
        production_order_id=po_code,
        part_id=part_code,
        lot_quantity=lot.lot_quantity,
        status=lot.status,
        dispatch_id=dispatch_code,
        final_quality_status=closure.final_quality_status if closure else None,
        closed_at=closure.closed_at if closure else None,
        nodes=nodes,
        edges=edges,
    )


def _build_graph(
    *,
    lot: str,
    po: str | None,
    order: str | None,
    customer: str | None,
    part: str | None,
    dispatch: str | None,
):
    nodes: List[TraceabilityNode] = []
    edges: List[TraceabilityEdge] = []
    if customer:
        nodes.append(TraceabilityNode(node_type="Customer", node_id=customer, label=customer))
    if order:
        nodes.append(TraceabilityNode(node_type="Order", node_id=order, label=order))
        if customer:
            edges.append(TraceabilityEdge(source=customer, target=order, predicate="places"))
    if part:
        nodes.append(TraceabilityNode(node_type="Part", node_id=part, label=part))
        if order:
            edges.append(TraceabilityEdge(source=order, target=part, predicate="for"))
    if po:
        nodes.append(TraceabilityNode(node_type="ProductionOrder", node_id=po, label=po))
        if order:
            edges.append(TraceabilityEdge(source=order, target=po, predicate="triggers"))
    nodes.append(TraceabilityNode(node_type="Lot", node_id=lot, label=lot))
    if po:
        edges.append(TraceabilityEdge(source=po, target=lot, predicate="splitsInto"))
    if dispatch:
        nodes.append(TraceabilityNode(node_type="Dispatch", node_id=dispatch, label=dispatch))
        edges.append(TraceabilityEdge(source=lot, target=dispatch, predicate="dispatchedThrough"))
    return nodes, edges
