"""Production usage trace for Activated Carbon raw material types."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core.execution import OperationExecution
from app.models.mes_core.transaction import (
    CustomerOrder,
    CustomerOrderLine,
    ProductionLot,
    ProductionOrder,
)
from app.services.mes_core.base import TenantRepository

# Shop-floor steps that lock routing edits (activation / pyrolysis — not kiln feed alone).
KILN_PROCESS_STEPS = frozenset({"KILN_FEED", "ACTIVATION", "PYROLYSIS"})
ROUTING_LOCK_PROCESS_STEPS = frozenset({"ACTIVATION", "PYROLYSIS"})

_EXECUTION_STARTED_STATUSES = frozenset(
    {"IN_PROGRESS", "COMPLETED", "DONE", "STARTED", "CLOSED"}
)

LOT_DISPATCHED_STATUSES = frozenset({"DISPATCHED", "SHIPPED"})


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _uuid_or_none(value) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _order_meta(order: CustomerOrder) -> dict:
    return order.metadata_ if isinstance(order.metadata_, dict) else {}


def _inward_order_ids_for_raw_product(
    db: Session, tenant: TenantContext, product_id: UUID
) -> set[UUID]:
    repo = _repo(db, tenant)
    product_key = str(product_id)
    inward_ids: set[UUID] = set()

    orders = repo.query(CustomerOrder).all()
    lines_by_order: dict[UUID, list[CustomerOrderLine]] = {}
    for line in repo.query(CustomerOrderLine).all():
        lines_by_order.setdefault(line.order_id, []).append(line)

    for order in orders:
        meta = _order_meta(order)
        if meta.get("flow") != "RAW_MATERIAL_INWARD":
            continue
        if meta.get("raw_product_id") == product_key:
            inward_ids.add(order.customer_order_id)
            continue
        for line in lines_by_order.get(order.customer_order_id, []):
            if str(line.product_id) == product_key:
                inward_ids.add(order.customer_order_id)
                break

    return inward_ids


def _production_lot_ids_for_inward_orders(
    db: Session, tenant: TenantContext, inward_ids: set[UUID]
) -> set[UUID]:
    if not inward_ids:
        return set()

    repo = _repo(db, tenant)
    inward_keys = {str(i) for i in inward_ids}
    lot_ids: set[UUID] = set()

    pos = repo.query(ProductionOrder).all()
    linked_po_ids: set[UUID] = set()
    for po in pos:
        meta = po.metadata_ if isinstance(po.metadata_, dict) else {}
        inward_id = meta.get("source_inward_order_id")
        if inward_id in inward_keys:
            linked_po_ids.add(po.production_order_id)

    lots = repo.query(ProductionLot).all()
    for lot in lots:
        if lot.production_order_id in linked_po_ids:
            lot_ids.add(lot.production_lot_id)

    return lot_ids


def _execution_process_step(row: OperationExecution) -> str:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return (
        meta.get("process_step")
        or meta.get("process_code")
        or meta.get("process_type")
        or ""
    ).upper()


def _execution_started(row: OperationExecution) -> bool:
    status = (row.status or "").upper()
    if row.started_at or row.completed_at:
        return True
    return status in _EXECUTION_STARTED_STATUSES and status != "NOT_STARTED"


def raw_material_usage(db: Session, tenant: TenantContext, product_id: UUID) -> dict:
    inward_ids = _inward_order_ids_for_raw_product(db, tenant, product_id)
    lot_ids = _production_lot_ids_for_inward_orders(db, tenant, inward_ids)

    kiln_process_started = False
    dispatch_completed = False

    if lot_ids:
        repo = _repo(db, tenant)
        executions = (
            repo.query(OperationExecution)
            .filter(OperationExecution.production_lot_id.in_(lot_ids))
            .all()
        )
        for ex in executions:
            step = _execution_process_step(ex)
            if step in ROUTING_LOCK_PROCESS_STEPS and _execution_started(ex):
                kiln_process_started = True
                break

        lots = (
            repo.query(ProductionLot)
            .filter(ProductionLot.production_lot_id.in_(lot_ids))
            .all()
        )
        for lot in lots:
            status = (lot.status or "").upper()
            lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
            if status in LOT_DISPATCHED_STATUSES or lot_meta.get("dispatched_at"):
                dispatch_completed = True
                break

        if not dispatch_completed:
            for order in repo.query(CustomerOrder).all():
                meta = _order_meta(order)
                dispatched = Decimal(str(meta.get("dispatched_kg") or 0))
                if dispatched > 0 and order.customer_order_id in inward_ids:
                    dispatch_completed = True
                    break

    locked = kiln_process_started or dispatch_completed or bool(lot_ids)
    return {
        "inward_receipt_count": len(inward_ids),
        "production_lot_count": len(lot_ids),
        "kiln_process_started": kiln_process_started,
        "dispatch_completed": dispatch_completed,
        "locked": locked,
    }
