"""Finished-goods stock and lot completion for Activated Carbon."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrder,
    CustomerOrderLine,
    OperationExecution,
    Product,
    ProductionLot,
    ProductionOrder,
    QualityCheck,
    Routing,
    RoutingOperation,
)
from app.services.industry.activated_carbon.resource_pool import (
    assert_resources_available,
    claim_execution_resources,
    kiln_release_step,
    release_execution_resources,
    release_lot_kiln_if_claimed,
    restore_execution_resources,
)
from app.services.mes_core.base import TenantRepository
from app.services.mes_core import execution_workflow as mes_core_execution

FG_STOCK_KEY = "fg_stock_kg"
QC_PASS_STATUSES = frozenset({"PASS", "PASSED", "QC_PASSED", "APPROVED", "CLOSED"})
REFERENCE_BATCH_KG = Decimal("1000")
_SCHEDULE_META_FLAG = "is_production_schedule"


def _is_schedule_row(row: OperationExecution) -> bool:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return bool(meta.get(_SCHEDULE_META_FLAG) or meta.get("schedule_code"))


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _execution_process_step(
    repo: TenantRepository, row: OperationExecution
) -> str:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    step = (meta.get("process_step") or "").strip()
    if step:
        return step.upper()
    if not row.routing_operation_id:
        return ""
    rop = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_operation_id == row.routing_operation_id)
        .first()
    )
    if not rop:
        return ""
    rop_meta = rop.metadata_ if isinstance(rop.metadata_, dict) else {}
    return (rop_meta.get("process_step") or "").upper()


def validate_resources_for_execution_start(
    db: Session,
    tenant: TenantContext,
    execution_code: str,
    payload,
) -> None:
    """Ensure machines, labor, and tools are free before shop-floor start."""
    repo = _repo(db, tenant)
    row = repo.get_by_code(
        OperationExecution, OperationExecution.execution_code, execution_code
    )
    if not _is_schedule_row(row):
        return
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, row.production_lot_id)
    rop = repo.get_by_pk(
        RoutingOperation,
        RoutingOperation.routing_operation_id,
        row.routing_operation_id,
    )
    selection = mes_core_execution.resolve_start_resource_selection(repo, rop, payload)
    assert_resources_available(
        db,
        tenant,
        lot_code=lot.lot_code,
        machine_code=selection.get("machine_code") or "",
        labor_code=selection.get("labor_pool_code") or "",
        tool_codes=selection.get("tool_codes") or [],
    )


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


def deduct_fg_stock_kg(
    db: Session, tenant: TenantContext, product_id: UUID, qty_kg: Decimal
) -> Decimal:
    from app.core.exceptions import ValidationError

    repo = _repo(db, tenant)
    product = repo.get_by_pk(Product, Product.product_id, product_id)
    meta = dict(_product_meta(product))
    current = Decimal(str(meta.get(FG_STOCK_KEY) or 0))
    qty = Decimal(str(qty_kg))
    if qty <= 0:
        raise ValidationError("Dispatch quantity must be greater than zero")
    if qty > current:
        raise ValidationError(
            f"Insufficient finished-goods stock for {product.product_code}: "
            f"available {current} KG, requested {qty} KG"
        )
    updated = current - qty
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
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, lot_id)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    if lot_meta.get("routing_complete_at"):
        return True

    rows = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot_id)
        .all()
    )
    work_orders = [r for r in rows if _is_schedule_row(r)]
    if not work_orders:
        st = (lot.status or "").upper()
        return st in ("QC_PENDING", "COMPLETED", "STOCKED")
    return all((r.status or "").upper() == "COMPLETED" for r in work_orders)


def lot_routing_complete(db: Session, tenant: TenantContext, lot_id: UUID) -> bool:
    """True when shop-floor routing is done (schedule ops and/or lot metadata)."""
    return _lot_executions_complete(db, tenant, lot_id)


def _execution_meta(row: OperationExecution) -> dict:
    return row.metadata_ if isinstance(row.metadata_, dict) else {}


def lot_has_screening(db: Session, tenant: TenantContext, lot_id: UUID) -> bool:
    rows = (
        _repo(db, tenant)
        .query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot_id)
        .all()
    )
    return any(_execution_meta(row).get("process_step") == "SCREENING" for row in rows)


def lot_has_passed_final_qc(db: Session, tenant: TenantContext, lot_id: UUID) -> bool:
    checks = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(QualityCheck.production_lot_id == lot_id)
        .all()
    )
    return any(qc_status_passed(check.status) for check in checks)


def try_stock_lot_after_pipeline(
    db: Session, tenant: TenantContext, production_lot_id: UUID
) -> Optional[Decimal]:
    """Move lot to finished-goods stock once routing, screening, and final QC are complete."""
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, production_lot_id)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    if lot_meta.get("fg_stocked") or (lot.status or "").upper() == "STOCKED":
        return Decimal(str(lot_meta.get("fg_stock_kg_added") or 0))

    if not lot_routing_complete(db, tenant, production_lot_id):
        return None
    if not lot_has_screening(db, tenant, production_lot_id):
        return None
    if not lot_has_passed_final_qc(db, tenant, production_lot_id):
        return None
    return stock_lot_after_final_qc(db, tenant, production_lot_id)


def reconcile_pending_stocked_lots(db: Session, tenant: TenantContext) -> int:
    """Release lots that passed QC + screening but were never stocked (e.g. pipeline fix)."""
    repo = _repo(db, tenant)
    released = 0
    for lot in repo.query(ProductionLot).all():
        st = (lot.status or "").upper()
        if st in ("STOCKED", "DISPATCHED", "SCRAPPED", "CLOSED", "CANCELLED"):
            continue
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        if lot_meta.get("fg_stocked"):
            continue
        if not lot_has_passed_final_qc(db, tenant, lot.production_lot_id):
            continue
        if not lot_has_screening(db, tenant, lot.production_lot_id):
            continue
        if not lot_routing_complete(db, tenant, lot.production_lot_id):
            continue
        if try_stock_lot_after_pipeline(db, tenant, lot.production_lot_id) is not None:
            released += 1
    return released


def scrap_lot_after_qc(
    db: Session, tenant: TenantContext, production_lot_id: UUID, *, reason: Optional[str] = None
) -> None:
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, production_lot_id)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    now = datetime.now(timezone.utc).isoformat()
    release_lot_schedule_resources(db, tenant, production_lot_id)
    lot.status = "SCRAPPED"
    lot.metadata_ = {
        **lot_meta,
        "scrapped_at": now,
        "scrap_reason": reason or "final_qc_reject",
    }
    repo.db.commit()


def release_lot_to_stock(
    db: Session, tenant: TenantContext, production_lot_id: UUID
) -> Decimal:
    """Explicit release after final QC — validates pipeline gates."""
    from app.core.exceptions import ValidationError

    if not lot_routing_complete(db, tenant, production_lot_id):
        raise ValidationError(
            "Shop-floor execution is not complete — finish all routing steps first."
        )
    if not lot_has_screening(db, tenant, production_lot_id):
        raise ValidationError("Screening is not recorded for this lot.")
    if not lot_has_passed_final_qc(db, tenant, production_lot_id):
        raise ValidationError("Final quality check must pass before release to stock.")
    qty = try_stock_lot_after_pipeline(db, tenant, production_lot_id)
    if qty is None:
        lot = _repo(db, tenant).get_by_pk(
            ProductionLot, ProductionLot.production_lot_id, production_lot_id
        )
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        if lot_meta.get("fg_stocked"):
            return Decimal(str(lot_meta.get("fg_stock_kg_added") or 0))
        raise ValidationError("Lot could not be released to stock.")
    return qty


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
    if kiln_release_step(_execution_process_step(repo, row)):
        release_lot_kiln_if_claimed(db, tenant, lot)

    lot_status = (lot.status or "").upper()
    if lot_status in ("COMPLETED", "DISPATCHED", "CLOSED", "STOCKED"):
        repo.db.commit()
        return

    if _lot_executions_complete(db, tenant, lot.production_lot_id):
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        lot.metadata_ = {
            **lot_meta,
            "routing_complete_at": datetime.now(timezone.utc).isoformat(),
        }
        lot.status = "QC_PENDING"
        release_lot_kiln_if_claimed(db, tenant, lot)
        release_lot_schedule_resources(db, tenant, lot.production_lot_id)
        try_stock_lot_after_pipeline(db, tenant, lot.production_lot_id)
        repo.db.commit()
        return

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
    """Move a QC-passed lot into finished-goods stock (once per lot).

    Clears kiln/labor schedule holds so the lot is dispatch-ready and resources
    can be booked for the next production run.
    """
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, production_lot_id)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    if lot_meta.get("fg_stocked"):
        return Decimal(str(lot_meta.get("fg_stock_kg_added") or 0))

    release_lot_schedule_resources(db, tenant, production_lot_id)

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


def on_execution_held(
    db: Session, tenant: TenantContext, execution_code: str
) -> None:
    repo = _repo(db, tenant)
    row = repo.get_by_code(
        OperationExecution, OperationExecution.execution_code, execution_code
    )
    if not _is_schedule_row(row) or not row.started_at:
        return
    release_execution_resources(db, tenant, row, for_hold=True)
    repo.db.commit()


def on_execution_resumed(
    db: Session, tenant: TenantContext, execution_code: str
) -> None:
    repo = _repo(db, tenant)
    row = repo.get_by_code(
        OperationExecution, OperationExecution.execution_code, execution_code
    )
    if not _is_schedule_row(row) or not row.started_at:
        return
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, row.production_lot_id)
    restore_execution_resources(db, tenant, row, lot_code=lot.lot_code)
    repo.db.commit()


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
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, lot_id)
    release_lot_kiln_if_claimed(db, tenant, lot)
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
        qc_ok = (order.status or "").upper() == "QC_PASSED" or qc_status_passed(
            qc.get("qc_status")
        )
        separation = (
            meta.get("grade_separation")
            if isinstance(meta.get("grade_separation"), dict)
            else {}
        )
        prep_ok = (separation.get("status") or "").upper() == "COMPLETED"
        if not qc_ok and not prep_ok:
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


def _rail_step_status(meta: dict, exec_key: str, fallback: dict | None) -> tuple[str, Optional[str]]:
    exec_map = meta.get("inbound_execution") if isinstance(meta.get("inbound_execution"), dict) else {}
    row = exec_map.get(exec_key)
    if isinstance(row, dict):
        status = str(row.get("status") or "").upper()
        decision = str(row.get("qc_decision") or row.get("qc_status") or "").upper()
        if exec_key == "IN-LAB" and (
            meta.get("inbound_lab_denied")
            or decision in ("DENY", "FAIL", "REJECTED", "DENIED")
        ):
            return "DENIED", row.get("completed_at") or row.get("qc_at")
        if status == "COMPLETED":
            return "COMPLETED", row.get("completed_at") or row.get("qc_at") or row.get("reconciled_at")
    if isinstance(fallback, dict):
        status = str(fallback.get("status") or fallback.get("qc_status") or "").upper()
        if status in ("FAIL", "QC_FAILED", "REJECTED", "DENIED"):
            return "DENIED", fallback.get("completed_at") or fallback.get("qc_at")
        if status in ("COMPLETED", "RECONCILED", "PASS", "QC_PASSED", "APPROVED"):
            return (
                "COMPLETED",
                fallback.get("completed_at")
                or fallback.get("qc_at")
                or fallback.get("reconciled_at"),
            )
    return "PENDING", None


def enrich_inward_order_stock(
    order_out,
    order_row,
    products: dict,
    *,
    released_at_fallback=None,
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
    qc = meta.get("raw_material_qc") if isinstance(meta.get("raw_material_qc"), dict) else {}
    qc_status = qc.get("qc_status")
    if not qc_status and (order_row.status or "").upper() == "QC_PASSED":
        qc_status = "QC_PASSED"
    receipt = meta.get("inward_receipt") if isinstance(meta.get("inward_receipt"), dict) else {}
    dc_number = receipt.get("dc_number")
    supplier_weight_kg = (
        Decimal(str(receipt["supplier_weight_kg"]))
        if receipt.get("supplier_weight_kg") is not None
        else None
    )
    our_weight_kg = (
        Decimal(str(receipt["our_weight_kg"]))
        if receipt.get("our_weight_kg") is not None
        else qty
    )
    supplier_value_inr = (
        Decimal(str(receipt["supplier_value_inr"]))
        if receipt.get("supplier_value_inr") is not None
        else None
    )
    initial_qc = meta.get("initial_qc") if isinstance(meta.get("initial_qc"), dict) else {}
    bags = meta.get("bag_reconciliation") if isinstance(meta.get("bag_reconciliation"), dict) else {}
    outward = meta.get("grade_separation") if isinstance(meta.get("grade_separation"), dict) else {}
    lab_status, lab_at = _rail_step_status(meta, "IN-LAB", initial_qc)
    rms_status, rms_at = _rail_step_status(meta, "IN-RMS-BAG", bags)
    out_status, out_at = _rail_step_status(meta, "IN-RM-OUT", outward)
    released_at = meta.get("released_to_production_at") or released_at_fallback
    released_status = "RELEASED" if allocated > 0 or released_at else "PENDING"
    if not isinstance(order_out, CustomerOrderOut):
        return order_out
    return order_out.model_copy(
        update={
            "raw_product_code": raw_code,
            "inward_quantity_kg": qty,
            "allocated_to_production_kg": allocated,
            "available_quantity_kg": available,
            "qc_status": qc_status or "PENDING",
            "dc_number": dc_number,
            "supplier_weight_kg": supplier_weight_kg,
            "our_weight_kg": our_weight_kg,
            "supplier_value_inr": supplier_value_inr,
            "lab_status": lab_status,
            "lab_at": lab_at,
            "rms_inward_status": rms_status,
            "rms_inward_at": rms_at,
            "rm_outward_status": out_status,
            "rm_outward_at": out_at,
            "released_to_production_status": released_status,
            "released_to_production_at": released_at,
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
    if not meta.get("released_to_production_at"):
        meta["released_to_production_at"] = datetime.now(timezone.utc).isoformat()
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    repo.db.flush()
    return max(line_qty - allocated - qty, Decimal("0"))
