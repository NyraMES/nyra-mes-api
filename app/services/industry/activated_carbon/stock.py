"""Finished-goods stock and lot completion for Activated Carbon."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrder,
    CustomerOrderLine,
    OperationExecution,
    Product,
    ProductionLot,
    ProductionOrder,
    Routing,
    RoutingOperation,
)
from app.services.industry.activated_carbon.resource_pool import (
    claim_execution_resources,
    release_execution_resources,
)
from app.services.mes_core.base import TenantRepository

FG_STOCK_KEY = "fg_stock_kg"
QC_PASS_STATUSES = frozenset({"PASS", "PASSED", "QC_PASSED", "APPROVED", "CLOSED"})
REFERENCE_BATCH_KG = Decimal("1000")
_SCHEDULE_META_FLAG = "is_production_schedule"


def _is_schedule_row(row: OperationExecution) -> bool:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return bool(meta.get(_SCHEDULE_META_FLAG) or meta.get("schedule_code"))


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _product_meta(product: Product) -> dict:
    return product.metadata_ if isinstance(product.metadata_, dict) else {}


def get_fg_stock_kg(db: Session, tenant: TenantContext, product_id: UUID) -> Decimal:
    product = _repo(db, tenant).get_by_pk(Product, Product.product_id, product_id)
    return Decimal(str(_product_meta(product).get(FG_STOCK_KEY) or 0))


def add_fg_stock_kg(
    db: Session, tenant: TenantContext, product_id: UUID, qty_kg: Decimal
) -> Decimal:
    repo = _repo(db, tenant)
    product = repo.get_by_pk(Product, Product.product_id, product_id)
    meta = dict(_product_meta(product))
    current = Decimal(str(meta.get(FG_STOCK_KEY) or 0))
    updated = current + qty_kg
    meta[FG_STOCK_KEY] = str(updated)
    product.metadata_ = meta
    repo.db.flush()
    return updated


def _lot_finished_product_id(
    db: Session, tenant: TenantContext, lot: ProductionLot
) -> Optional[UUID]:
    repo = _repo(db, tenant)
    po = repo.get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, lot.production_order_id
    )
    line = repo.get_by_pk(
        CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
    )
    return line.product_id


def _lot_executions_complete(db: Session, tenant: TenantContext, lot_id: UUID) -> bool:
    rows = (
        _repo(db, tenant)
        .query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot_id)
        .all()
    )
    work_orders = [r for r in rows if _is_schedule_row(r)]
    if not work_orders:
        return False
    return all((r.status or "").upper() == "COMPLETED" for r in work_orders)


def after_execution_completed(
    db: Session, tenant: TenantContext, execution_code: str
) -> None:
    """Release resources for the finished step; when routing is done, await final QC."""
    repo = _repo(db, tenant)
    try:
        row = repo.get_by_code(
            OperationExecution, OperationExecution.execution_code, execution_code
        )
        if not _is_schedule_row(row):
            return
    except Exception:
        return

    release_execution_resources(db, tenant, row)

    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, row.production_lot_id)
    lot_status = (lot.status or "").upper()
    if lot_status in ("COMPLETED", "DISPATCHED", "CLOSED", "STOCKED"):
        repo.db.commit()
        return

    if _lot_executions_complete(db, tenant, lot.production_lot_id):
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        lot.status = "QC_PENDING"
        lot.metadata_ = {
            **lot_meta,
            "routing_complete_at": datetime.now(timezone.utc).isoformat(),
        }
        release_lot_schedule_resources(db, tenant, lot.production_lot_id)
    repo.db.commit()


def after_work_order_completed(
    db: Session, tenant: TenantContext, execution_code: str
) -> None:
    """Backward-compatible alias for mes_core complete hook."""
    after_execution_completed(db, tenant, execution_code)


def qc_status_passed(status: Optional[str]) -> bool:
    return (status or "").upper() in QC_PASS_STATUSES


def stock_lot_after_final_qc(
    db: Session,
    tenant: TenantContext,
    production_lot_id: UUID,
    *,
    quantity_kg: Optional[Decimal] = None,
) -> Optional[Decimal]:
    """Move a QC-passed lot into finished-goods stock (once per lot)."""
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, production_lot_id)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    if lot_meta.get("fg_stocked"):
        return Decimal(str(lot_meta.get("fg_stock_kg_added") or 0))

    product_id = _lot_finished_product_id(db, tenant, lot)
    if not product_id:
        return None

    qty = quantity_kg if quantity_kg is not None else Decimal(str(lot.lot_quantity or 0))
    if qty <= 0:
        return None

    updated = add_fg_stock_kg(db, tenant, product_id, qty)
    now = datetime.now(timezone.utc).isoformat()
    lot.status = "STOCKED"
    lot.metadata_ = {
        **lot_meta,
        "fg_stocked": True,
        "stocked_at": now,
        "fg_stock_kg_added": str(qty),
        "qc_passed_at": now,
    }
    repo.db.commit()
    return updated


def on_execution_started(
    db: Session, tenant: TenantContext, execution_code: str
) -> None:
    repo = _repo(db, tenant)
    row = repo.get_by_code(
        OperationExecution, OperationExecution.execution_code, execution_code
    )
    if not _is_schedule_row(row):
        return
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, row.production_lot_id)
    claim_execution_resources(db, tenant, row, lot_code=lot.lot_code)
    repo.db.commit()


def release_lot_schedule_resources(
    db: Session, tenant: TenantContext, lot_id: UUID
) -> None:
    """Clear kiln/labor schedule holds so feasibility can book the next lot."""
    repo = _repo(db, tenant)
    now = datetime.now(timezone.utc).isoformat()
    rows = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot_id)
        .all()
    )
    for row in rows:
        if not _is_schedule_row(row):
            continue
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if not meta.get("resources_released"):
            release_execution_resources(db, tenant, row)
            meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        meta = {
            **meta,
            "resources_released": True,
            "resources_released_at": now,
        }
        meta.pop("planned_start_time", None)
        meta.pop("planned_end_time", None)
        row.metadata_ = meta
    repo.db.flush()


def _routing_lead_minutes(db: Session, tenant: TenantContext, product_id: UUID) -> float:
    repo = _repo(db, tenant)
    routing = (
        repo.query(Routing)
        .filter(Routing.product_id == product_id, Routing.is_active.is_(True))
        .order_by(Routing.routing_version.desc())
        .first()
    )
    if not routing:
        routing = (
            repo.query(Routing)
            .filter(Routing.is_active.is_(True))
            .order_by(Routing.routing_version.desc())
            .first()
        )
    if not routing:
        return 24 * 60.0
    ops = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .all()
    )
    total = 0.0
    for op in ops:
        if op.standard_cycle_min is not None:
            total += float(op.standard_cycle_min)
    return total if total > 0 else 24 * 60.0


def estimate_manufacturing_days(
    db: Session, tenant: TenantContext, product_id: UUID, quantity_kg: Decimal
) -> int:
    cycle_min = _routing_lead_minutes(db, tenant, product_id)
    scale = max(float(quantity_kg) / float(REFERENCE_BATCH_KG), 0.25)
    scaled_min = cycle_min * scale
    shop_days = int((scaled_min / (60.0 * 8.0)) + 0.999)
    return max(3, shop_days + 2)


def available_raw_material_kg(db: Session, tenant: TenantContext) -> Decimal:
    """QC-passed inward receipts not yet allocated to make-to-stock."""
    repo = _repo(db, tenant)
    total = Decimal("0")
    orders = repo.query(CustomerOrder).all()
    for order in orders:
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        if meta.get("flow") != "RAW_MATERIAL_INWARD":
            continue
        qc = meta.get("raw_material_qc") if isinstance(meta.get("raw_material_qc"), dict) else {}
        qc_ok = (order.status or "").upper() == "QC_PASSED" or qc.get("qc_status") in (
            "PASS",
            "PASSED",
        )
        if not qc_ok:
            continue
        allocated = Decimal(str(meta.get("allocated_to_production_kg") or 0))
        lines = (
            repo.query(CustomerOrderLine)
            .filter(CustomerOrderLine.order_id == order.customer_order_id)
            .all()
        )
        products = {p.product_id: p for p in repo.query(Product).all()}
        for line in lines:
            product = products.get(line.product_id)
            if not product:
                continue
            code = (product.product_code or "").upper()
            ptype = (product.product_type or "").upper()
            if ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-"):
                line_qty = Decimal(str(line.quantity or 0))
                total += max(line_qty - allocated, Decimal("0"))
    return total


def _raw_line_quantity(
    order_lines: list, products: dict
) -> tuple[Decimal, Optional[str]]:
    """Return (qty_kg, raw_product_code) from the first raw-material line."""
    for line in order_lines:
        product = products.get(getattr(line, "product_id", None))
        code = (getattr(line, "product_code", None) or "").upper()
        if product:
            code = (product.product_code or code).upper()
            ptype = (product.product_type or "").upper()
            if ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-"):
                return Decimal(str(getattr(line, "quantity", 0) or 0)), product.product_code
        if code.startswith("RAW-"):
            return Decimal(str(getattr(line, "quantity", 0) or 0)), code
    if order_lines:
        line = order_lines[0]
        return Decimal(str(getattr(line, "quantity", 0) or 0)), getattr(line, "product_code", None)
    return Decimal("0"), None


def enrich_inward_order_stock(
    order_out,
    order_row,
    products: dict,
):
    """Attach quantity / allocated / available fields for raw material inward UI."""
    from app.schemas.mes_core.schemas import CustomerOrderOut

    meta = order_row.metadata_ if isinstance(order_row.metadata_, dict) else {}
    allocated = Decimal(str(meta.get("allocated_to_production_kg") or 0))

    qty = Decimal("0")
    raw_code = None
    for line in order_out.lines or []:
        product = products.get(line.product_id)
        code = (line.product_code or "").upper()
        if product:
            code = (product.product_code or code).upper()
        if code.startswith("RAW-") or (
            product
            and (product.product_type or "").upper() in ("RAW_MATERIAL", "RAW")
        ):
            qty = Decimal(str(line.quantity or 0))
            raw_code = line.product_code or (product.product_code if product else None)
            break
    if qty <= 0 and order_out.lines:
        line = order_out.lines[0]
        qty = Decimal(str(line.quantity or 0))
        raw_code = line.product_code

    available = max(qty - allocated, Decimal("0"))
    if not isinstance(order_out, CustomerOrderOut):
        return order_out
    return order_out.model_copy(
        update={
            "raw_product_code": raw_code,
            "inward_quantity_kg": qty,
            "allocated_to_production_kg": allocated,
            "available_quantity_kg": available,
        }
    )


def allocate_raw_from_inward(
    db: Session,
    tenant: TenantContext,
    inward_order_id: UUID,
    quantity_kg: Decimal,
) -> Decimal:
    """Reserve inward qty for make-to-stock; returns remaining available kg."""
    from app.core.exceptions import ValidationError

    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, inward_order_id
    )
    products = {p.product_id: p for p in repo.query(Product).all()}
    lines = (
        repo.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == inward_order_id)
        .all()
    )
    line_qty, _ = _raw_line_quantity(lines, products)
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    allocated = Decimal(str(meta.get("allocated_to_production_kg") or 0))
    available = max(line_qty - allocated, Decimal("0"))
    qty = Decimal(str(quantity_kg))
    if qty <= 0:
        raise ValidationError("Release quantity must be greater than zero")
    if qty > available:
        raise ValidationError(
            f"Only {available} KG available on this inward receipt "
            f"({line_qty} KG received, {allocated} KG already released to production)"
        )
    meta = {
        **meta,
        "allocated_to_production_kg": str(allocated + qty),
    }
    order.metadata_ = meta
    repo.db.flush()
    return max(line_qty - allocated - qty, Decimal("0"))
