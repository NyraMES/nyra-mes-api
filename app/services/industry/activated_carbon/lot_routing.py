"""Resolve shop-floor routing from the raw material type linked to a production lot."""

from __future__ import annotations

from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrder,
    CustomerOrderLine,
    Product,
    ProductionLot,
    ProductionOrder,
    Routing,
    RoutingOperation,
)
from app.services.industry.activated_carbon import raw_material_types as ac_raw_material_types
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.routing_helpers import _ordered_routing_operations, load_lot_routing


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _uuid_or_none(value) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def resolve_raw_material_type_for_lot(
    db: Session, tenant: TenantContext, lot: ProductionLot
):
    """Find the Masters raw material type for this lot (via inward → raw product)."""
    repo = _repo(db, tenant)
    po = repo.get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, lot.production_order_id
    )
    po_meta = po.metadata_ if isinstance(po.metadata_, dict) else {}

    raw_product_id = _uuid_or_none(po_meta.get("raw_product_id"))
    if not raw_product_id:
        inward_id = _uuid_or_none(po_meta.get("source_inward_order_id"))
        if inward_id:
            inward = repo.get_by_pk(
                CustomerOrder, CustomerOrder.customer_order_id, inward_id
            )
            imeta = inward.metadata_ if isinstance(inward.metadata_, dict) else {}
            raw_product_id = _uuid_or_none(imeta.get("raw_product_id"))

    if raw_product_id:
        try:
            return ac_raw_material_types.get_raw_material_type(
                db, tenant, raw_product_id
            )
        except NotFoundError:
            pass

    routing_id = _uuid_or_none(po_meta.get("routing_id"))
    if routing_id:
        line = repo.get_by_pk(
            CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
        )
        finished = repo.get_by_pk(Product, Product.product_id, line.product_id)
        fg_code = (finished.product_code or "").upper()
        for typed in ac_raw_material_types.list_raw_material_types(db, tenant):
            if (typed.finished_product_code or "").upper() == fg_code:
                return typed
            if typed.routing_id == routing_id:
                return typed

    line = repo.get_by_pk(
        CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
    )
    finished = repo.get_by_pk(Product, Product.product_id, line.product_id)
    fg_code = (finished.product_code or "").upper()
    for typed in ac_raw_material_types.list_raw_material_types(db, tenant):
        if typed.finished_product_id == finished.product_id:
            return typed
        if (typed.finished_product_code or "").upper() == fg_code:
            return typed
    return None


def production_order_meta_for_raw(
    db: Session, tenant: TenantContext, raw_product_id: UUID
) -> dict[str, str]:
    """Stamp PO metadata so lots inherit the correct FG product and routing."""
    meta: dict[str, str] = {"raw_product_id": str(raw_product_id)}
    try:
        typed = ac_raw_material_types.get_raw_material_type(
            db, tenant, raw_product_id
        )
        if typed.finished_product_id:
            meta["finished_product_id"] = str(typed.finished_product_id)
        if typed.routing_id:
            meta["routing_id"] = str(typed.routing_id)
        if typed.finished_product_code:
            meta["finished_product_code"] = typed.finished_product_code
        if typed.routing_code:
            meta["routing_code"] = typed.routing_code
    except NotFoundError:
        pass
    return meta


def load_ac_lot_routing(
    db: Session, tenant: TenantContext, lot: ProductionLot
) -> Tuple[Optional[Product], Optional[Routing], list[RoutingOperation], float]:
    """Load routing for a lot, preferring the raw material type's linked routing."""
    repo = _repo(db, tenant)
    product, routing, operations, qty = load_lot_routing(repo, lot)

    typed = resolve_raw_material_type_for_lot(db, tenant, lot)
    if not typed or not typed.routing_id:
        return product, routing, operations, qty

    try:
        typed_routing = repo.get_by_pk(Routing, Routing.routing_id, typed.routing_id)
    except NotFoundError:
        return product, routing, operations, qty

    typed_operations = _ordered_routing_operations(
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == typed.routing_id)
        .all()
    )
    if not typed_operations:
        return product, routing, operations, qty

    if typed.finished_product_id:
        try:
            product = repo.get_by_pk(
                Product, Product.product_id, typed.finished_product_id
            )
        except NotFoundError:
            pass

    return product, typed_routing, typed_operations, qty
