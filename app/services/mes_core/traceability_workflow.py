"""Lot traceability / genealogy for nyra_mes_core."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    Customer,
    CustomerOrder,
    CustomerOrderLine,
    Product,
    ProductionLot,
    ProductionOrder,
    QualityCheck,
)
from app.schemas.traceability import TraceabilityEdge, TraceabilityNode, TraceabilityResponse
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.quality_workflow import list_inspection_results

_DISPATCH_TYPE = "DISPATCH"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _meta(row: QualityCheck) -> dict:
    data = row.metadata_ or {}
    return data if isinstance(data, dict) else {}


def _build_graph(
    *,
    lot: str,
    po: str | None,
    order: str | None,
    customer: str | None,
    part: str | None,
    dispatch: str | None,
) -> tuple[List[TraceabilityNode], List[TraceabilityEdge]]:
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
        edges.append(
            TraceabilityEdge(source=lot, target=dispatch, predicate="dispatchedThrough")
        )
    return nodes, edges


def _find_dispatch_code(
    db: Session, tenant: TenantContext, lot_code: str, lot_pk
) -> Optional[str]:
    repo = _repo(db, tenant)
    rows = (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type == _DISPATCH_TYPE)
        .order_by(QualityCheck.created_at.desc())
        .all()
    )
    for row in rows:
        if row.production_lot_id == lot_pk:
            return row.check_code
        lines = _meta(row).get("lines") or []
        if isinstance(lines, list) and any(
            isinstance(line, dict) and line.get("lot_id") == lot_code for line in lines
        ):
            return row.check_code
    return None


def _final_quality_for_lot(
    db: Session, tenant: TenantContext, lot_code: str
) -> tuple[Optional[str], Optional[datetime]]:
    inspections = [
        r
        for r in list_inspection_results(db, tenant)
        if r.lot_id == lot_code
    ]
    if not inspections:
        return None, None
    inspections.sort(
        key=lambda r: r.inspected_at.timestamp() if r.inspected_at else 0,
        reverse=True,
    )
    latest = inspections[0]
    return latest.inspection_status, latest.inspected_at


def get_traceability(
    db: Session, tenant: TenantContext, lot_code: str
) -> TraceabilityResponse:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)

    po_code: Optional[str] = None
    order_code: Optional[str] = None
    customer_code: Optional[str] = None
    part_code: Optional[str] = None

    po = repo.get_by_pk(
        ProductionOrder,
        ProductionOrder.production_order_id,
        lot.production_order_id,
    )
    po_code = po.production_order_code

    line = repo.get_by_pk(
        CustomerOrderLine,
        CustomerOrderLine.order_line_id,
        po.order_line_id,
    )
    order = repo.get_by_pk(
        CustomerOrder,
        CustomerOrder.customer_order_id,
        line.order_id,
    )
    order_code = order.order_code

    customer = repo.get_by_pk(
        Customer,
        Customer.customer_id,
        order.customer_id,
    )
    customer_code = customer.customer_code

    product = repo.get_by_pk(Product, Product.product_id, line.product_id)
    part_code = product.product_code

    dispatch_code = _find_dispatch_code(
        db, tenant, lot_code, lot.production_lot_id
    )
    final_quality, quality_at = _final_quality_for_lot(db, tenant, lot_code)

    closed_at = None
    if dispatch_code:
        dispatch_row = repo.get_by_code(QualityCheck, QualityCheck.check_code, dispatch_code)
        closed_at = dispatch_row.created_at
    elif quality_at:
        closed_at = quality_at

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
        final_quality_status=final_quality,
        closed_at=closed_at,
        nodes=nodes,
        edges=edges,
    )
