"""Activated Carbon industry adapter — reuses common nyra_mes_core MES tables."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError, WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    Customer,
    CustomerOrder,
    CustomerOrderLine,
    Equipment,
    FeasibilityCheck,
    OperationExecution,
    Product,
    ProductionLot,
    ProductionOrder,
    QualityCheck,
    Resource,
    Routing,
    RoutingOperation,
    TripleStoreStaging,
)
from app.schemas.mes_core.schemas import (
    AcActiveOrderOut,
    AcDashboardOut,
    AcLotLineOut,
    AcOpenLotOut,
    AcKilnFeedLotCreate,
    AcKilnCreate,
    AcKilnOut,
    AcPlantResourceOut,
    AcKilnParametersCreate,
    AcKilnStatusOut,
    AcMastersOut,
    AcProcessStepOut,
    AcQualityTestCreate,
    AcCustomerSalesOrderCreate,
    AcCustomerSalesOrderCreateResponse,
    AcDispatchFromOrderCreate,
    AcDispatchFromOrderResponse,
    AcGradeStockOut,
    AcOpenCustomerOrderOut,
    AcRecentDispatchOut,
    AcStockedLotOut,
    AcFinishedGoodsStockOut,
    AcMakeToStockCreate,
    AcMakeToStockCreateResponse,
    AcRawMaterialInwardCreate,
    AcRawMaterialInwardCreateResponse,
    AcRawMaterialQcCreate,
    AcRawMaterialQcOut,
    AcRawMaterialStatusOut,
    AcRoutingMasterOut,
    AcRoutingOperationSummary,
    AcScreeningCreate,
    ActivatedCarbonYieldSummaryOut,
    CustomerCreate,
    CustomerOut,
    CustomerOrderCreate,
    CustomerOrderLineCreate,
    CustomerOrderOut,
    InwardOrderCreate,
    OperationExecutionOut,
    ProductionLotCreate,
    ProductionLotOut,
    ProductionOrderCreate,
    ProductionOrderOut,
    QualityCheckCreate,
    QualityCheckOut,
    ResourceCreate,
    ResourceOut,
    SupplierCreate,
    SupplierOut,
    TripleCreate,
    TripleOut,
)
from app.services.industry.activated_carbon.codes import (
    AC_ID_PAD_WIDTH,
    resolve_ac_business_code,
    sync_ac_sequences,
)
from app.services.industry.activated_carbon.constants import (
    AC_PROCESS_COUNT_KEYS,
    AC_PROCESS_FLOW,
    FINISHED_PRODUCT_CODE,
    ROUTING_CODE,
)
from app.services.industry.activated_carbon.kiln_parameters_catalog import (
    list_kiln_parameter_definitions,
)
from app.services.industry.activated_carbon import raw_material_types as ac_raw_material_types
from app.services.industry.activated_carbon import stock as ac_stock
from app.schemas.traceability import TraceabilityResponse
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.feasibility import is_ready_for_scheduling
from app.services.mes_core import dispatch_workflow as mes_core_dispatch
from app.services.mes_core import traceability_workflow as mes_core_traceability
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _headcount_from_metadata(meta: object) -> Optional[int]:
    if not isinstance(meta, dict):
        return None
    for key in ("headcount", "operators", "capacity", "available_count"):
        if meta.get(key) is not None:
            try:
                return int(meta[key])
            except (TypeError, ValueError):
                continue
    return None


def _resource_out(row: Resource) -> ResourceOut:
    return ResourceOut(
        resource_id=row.resource_id,
        tenant_id=row.tenant_id,
        resource_code=row.resource_code,
        resource_name=row.resource_name,
        resource_type=row.resource_type,
        status=row.status,
        headcount=_headcount_from_metadata(row.metadata_),
        created_at=row.created_at,
    )


def create_ac_customer(
    db: Session, tenant: TenantContext, payload: CustomerCreate
) -> CustomerOut:
    """Create customer with CUST-AC-* code when code is omitted."""
    sync_ac_sequences(db, tenant.tenant_id)
    code = resolve_ac_business_code(
        db, provided=payload.customer_code, entity="ac_customer"
    )
    return mes_core_entities.create_customer(
        db,
        tenant,
        CustomerCreate(
            customer_code=code,
            customer_name=payload.customer_name,
            status=payload.status,
        ),
    )


def create_ac_supplier(
    db: Session, tenant: TenantContext, payload: SupplierCreate
) -> SupplierOut:
    """Create supplier with SUP-AC-* code when code is omitted."""
    sync_ac_sequences(db, tenant.tenant_id)
    code = resolve_ac_business_code(
        db, provided=payload.supplier_code, entity="ac_supplier"
    )
    return mes_core_entities.create_supplier(
        db,
        tenant,
        SupplierCreate(
            supplier_code=code,
            supplier_name=payload.supplier_name,
            status=payload.status,
        ),
    )


def _tenant_resources(db: Session, tenant: TenantContext):
    """All resources for tenant — codes are unique per tenant, not per workspace."""
    return db.query(Resource).filter(Resource.tenant_id == tenant.tenant_id)


def _tenant_equipment(db: Session, tenant: TenantContext):
    return db.query(Equipment).filter(Equipment.tenant_id == tenant.tenant_id)


def _list_tenant_kiln_resources(db: Session, tenant: TenantContext) -> list[Resource]:
    """Kilns are plant-wide; list by RES-KILN* across the tenant."""
    kiln_rows = (
        _tenant_resources(db, tenant)
        .filter(Resource.resource_code.like("RES-KILN%"))
        .order_by(Resource.resource_code)
        .all()
    )
    if kiln_rows:
        return kiln_rows
    repo = _repo(db, tenant)
    return (
        repo.query(Resource)
        .filter(Resource.resource_type == "MACHINE")
        .order_by(Resource.resource_code)
        .all()
    )


def _resolve_finished_product(repo: TenantRepository) -> Product:
    try:
        return repo.get_by_code(Product, Product.product_code, FINISHED_PRODUCT_CODE)
    except Exception:
        routing = (
            repo.query(Routing)
            .filter(Routing.is_active.is_(True))
            .order_by(Routing.routing_version.desc())
            .first()
        )
        if not routing:
            raise ValueError(
                f"No finished product or active routing — run seed with --install-master "
                f"({ROUTING_CODE} / {FINISHED_PRODUCT_CODE})"
            )
        return repo.get_by_pk(Product, Product.product_id, routing.product_id)


def _routable_product_ids(repo: TenantRepository) -> set:
    rows = (
        repo.query(Routing)
        .filter(Routing.is_active.is_(True))
        .all()
    )
    return {row.product_id for row in rows if row.product_id is not None}


def _order_for_production_line(
    repo: TenantRepository, line: CustomerOrderLine
) -> Optional[CustomerOrder]:
    return (
        repo.query(CustomerOrder)
        .filter(CustomerOrder.customer_order_id == line.order_id)
        .first()
    )


def _production_order_eligible_for_kiln(
    db: Session, tenant: TenantContext, po: ProductionOrderOut
) -> bool:
    repo = _repo(db, tenant)
    line = repo.get_by_pk(
        CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
    )
    order = _order_for_production_line(repo, line)
    if not order:
        return True
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    flow = (meta.get("flow") or "").upper()
    if flow == "CUSTOMER_SALES":
        return False
    if flow == "MAKE_TO_STOCK":
        # Legacy duplicate PO from old release flow — prefer inward-linked PO.
        return False
    if flow == "RAW_MATERIAL_INWARD":
        product = repo.get_by_pk(Product, Product.product_id, line.product_id)
        return not _is_raw_product(product)
    if order.customer_id is not None and flow != "MAKE_TO_STOCK":
        return False
    routable = _routable_product_ids(repo)
    return line.product_id in routable


def _production_orders_with_routing(
    db: Session, tenant: TenantContext,
) -> List[ProductionOrderOut]:
    repo = _repo(db, tenant)
    routable = _routable_product_ids(repo)
    if not routable:
        return [
            po
            for po in mes_core_entities.list_production_orders(db, tenant)
            if _production_order_eligible_for_kiln(db, tenant, po)
        ]
    orders: list[ProductionOrderOut] = []
    for po in mes_core_entities.list_production_orders(db, tenant):
        line = repo.get_by_pk(
            CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
        )
        if line.product_id in routable and _production_order_eligible_for_kiln(
            db, tenant, po
        ):
            orders.append(po)
    return orders


def _resolve_finished_product_for_raw(
    db: Session, tenant: TenantContext, raw_product_id: UUID
) -> Product:
    repo = _repo(db, tenant)
    for typed in ac_raw_material_types.list_raw_material_types(db, tenant):
        if typed.product_id == raw_product_id and typed.finished_product_id:
            return repo.get_by_pk(
                Product, Product.product_id, typed.finished_product_id
            )
        if typed.product_id == raw_product_id and typed.finished_product_code:
            return repo.get_by_code(
                Product, Product.product_code, typed.finished_product_code
            )
    return _resolve_finished_product(repo)


def _routing_master_summary(db: Session, tenant: TenantContext) -> Optional[AcRoutingMasterOut]:
    repo = _repo(db, tenant)
    routing = (
        repo.query(Routing)
        .filter(Routing.routing_code == ROUTING_CODE, Routing.is_active.is_(True))
        .first()
    )
    if not routing:
        routing = (
            repo.query(Routing)
            .filter(
                Routing.is_template_copy.is_(True),
                Routing.is_active.is_(True),
            )
            .order_by(Routing.created_at.desc())
            .first()
        )
    if not routing:
        routing = (
            db.query(Routing)
            .filter(
                Routing.tenant_id == tenant.tenant_id,
                Routing.routing_code == "AC_STANDARD_PROCESS",
                Routing.is_template_route.is_(True),
                Routing.is_active.is_(True),
            )
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
        return None

    product_code: Optional[str] = None
    product_name: Optional[str] = None
    if routing.product_id:
        product = repo.get_by_pk(Product, Product.product_id, routing.product_id)
        product_code = product.product_code
        product_name = product.product_name
    else:
        finished = (
            repo.query(Product)
            .filter(Product.product_code == FINISHED_PRODUCT_CODE)
            .first()
        )
        if finished:
            product_code = finished.product_code
            product_name = finished.product_name

    ops = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    return AcRoutingMasterOut(
        routing_code=routing.routing_code,
        routing_version=routing.routing_version,
        product_code=product_code,
        product_name=product_name,
        operations=[
            AcRoutingOperationSummary(
                operation_code=op.operation_code,
                operation_sequence=op.operation_sequence,
                operation_name=op.operation_name,
                process_step=(op.metadata_ or {}).get("process_step")
                if isinstance(op.metadata_, dict)
                else op.operation_type,
            )
            for op in ops
        ],
    )


# --- Raw material inward (supplier receipt / production demand) ---


def list_raw_material_inward(
    db: Session, tenant: TenantContext
) -> List[CustomerOrderOut]:
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    rows = (
        repo.query(CustomerOrder)
        .order_by(CustomerOrder.created_at.desc())
        .all()
    )
    out: List[CustomerOrderOut] = []
    for row in rows:
        order_out = mes_core_entities._customer_order_out(db, tenant, row)
        if _order_is_raw_material_inward(row, order_out, products):
            out.append(ac_stock.enrich_inward_order_stock(order_out, row, products))
    return out


def _order_is_raw_material_inward(
    order: CustomerOrder,
    order_out: CustomerOrderOut,
    products: dict,
) -> bool:
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    if meta.get("flow") == "RAW_MATERIAL_INWARD":
        return True
    for line in order_out.lines or []:
        product = products.get(line.product_id)
        if product and _is_raw_product(product):
            return True
        code = (line.product_code or "").upper()
        if code.startswith("RAW-"):
            return True
    return False


def _require_raw_material_inward_order(
    db: Session, tenant: TenantContext, order: CustomerOrder
) -> CustomerOrder:
    """Validate inward receipt; backfill metadata.flow when inferred from raw lines."""
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    order_out = mes_core_entities._customer_order_out(db, tenant, order)
    if not _order_is_raw_material_inward(order, order_out, products):
        raise ValidationError("Order is not a raw material inward receipt")
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    if meta.get("flow") != "RAW_MATERIAL_INWARD":
        raw_line = next(
            (
                line
                for line in order_out.lines or []
                if (products.get(line.product_id) and _is_raw_product(products[line.product_id]))
                or (line.product_code or "").upper().startswith("RAW-")
            ),
            None,
        )
        order.metadata_ = {
            **meta,
            "flow": "RAW_MATERIAL_INWARD",
            **({"raw_product_id": str(raw_line.product_id)} if raw_line else {}),
        }
        repo.db.flush()
    return order


def _customer_order_has_raw_line(order: CustomerOrderOut) -> bool:
    """Legacy helper — prefer _order_is_raw_material_inward for DB-backed checks."""
    for line in order.lines or []:
        code = (line.product_code or "").upper()
        if code.startswith("RAW-"):
            return True
    return False


def list_kiln_feed_lots(db: Session, tenant: TenantContext) -> List[ProductionLotOut]:
    return mes_core_entities.list_production_lots(db, tenant)


def list_kiln_production_orders(
    db: Session, tenant: TenantContext
) -> List[ProductionOrderOut]:
    return _production_orders_with_routing(db, tenant)


def list_finished_goods_stock(
    db: Session, tenant: TenantContext
) -> List[AcFinishedGoodsStockOut]:
    repo = _repo(db, tenant)
    routable = _routable_product_ids(repo)
    rows = repo.query(Product).order_by(Product.product_code).all()
    out: list[AcFinishedGoodsStockOut] = []
    for row in rows:
        if row.product_id not in routable:
            code = (row.product_code or "").upper()
            if code != FINISHED_PRODUCT_CODE:
                continue
        qty = ac_stock.get_fg_stock_kg(db, tenant, row.product_id)
        if qty <= 0:
            continue
        out.append(
            AcFinishedGoodsStockOut(
                product_id=row.product_id,
                product_code=row.product_code,
                product_name=row.product_name,
                quantity_kg=qty,
                uom=row.uom or "KG",
            )
        )
    return out


def evaluate_delivery_commitment(
    db: Session,
    tenant: TenantContext,
    *,
    finished_product_id: UUID,
    quantity: Decimal,
) -> AcDeliveryCommitmentOut:
    repo = _repo(db, tenant)
    product = repo.get_by_pk(Product, Product.product_id, finished_product_id)
    stock = ac_stock.get_fg_stock_kg(db, tenant, finished_product_id)
    qty = Decimal(str(quantity))
    shortfall = max(qty - stock, Decimal("0"))
    raw_avail = ac_stock.available_raw_material_kg(db, tenant)
    today = date.today()

    if shortfall <= 0:
        return AcDeliveryCommitmentOut(
            finished_product_id=finished_product_id,
            product_code=product.product_code,
            quantity_kg=qty,
            stock_on_hand_kg=stock,
            can_dispatch_from_stock=True,
            shortfall_kg=Decimal("0"),
            raw_material_available_kg=raw_avail,
            tentative_delivery_date=today,
            manufacturing_lead_days=0,
            message=(
                f"{stock} KG in finished-goods stock — quantity can be dispatched without "
                "new production."
            ),
        )

    lead_days = ac_stock.estimate_manufacturing_days(
        db, tenant, finished_product_id, shortfall
    )
    tentative = today + timedelta(days=lead_days)
    if raw_avail < shortfall:
        message = (
            f"Stock covers {stock} KG; need {shortfall} KG more. Raw material on hand "
            f"({raw_avail} KG) is insufficient — procure feedstock before promising "
            f"{tentative.isoformat()}."
        )
    else:
        message = (
            f"Stock covers {stock} KG; manufacturing ~{lead_days} shop days for "
            f"{shortfall} KG from available raw material — tentative delivery "
            f"{tentative.isoformat()}."
        )

    return AcDeliveryCommitmentOut(
        finished_product_id=finished_product_id,
        product_code=product.product_code,
        quantity_kg=qty,
        stock_on_hand_kg=stock,
        can_dispatch_from_stock=False,
        shortfall_kg=shortfall,
        raw_material_available_kg=raw_avail,
        tentative_delivery_date=tentative,
        manufacturing_lead_days=lead_days,
        message=message,
    )


def create_customer_sales_order(
    db: Session, tenant: TenantContext, payload: AcCustomerSalesOrderCreate
) -> AcCustomerSalesOrderCreateResponse:
    sync_ac_sequences(db, tenant.tenant_id)
    order_code = resolve_ac_business_code(
        db, provided=payload.order_code, entity="ac_customer_order"
    )
    line_code = resolve_ac_business_code(
        db, provided=None, entity="ac_customer_order_line"
    )
    metadata: dict = {
        "flow": "CUSTOMER_SALES",
        "product_id": str(payload.finished_product_id),
        "ordered_kg": str(payload.quantity),
        "dispatched_kg": "0",
    }
    if payload.requested_delivery_date:
        metadata["delivery_date"] = payload.requested_delivery_date.isoformat()

    order_resp = mes_core_entities.create_customer_order(
        db,
        tenant,
        CustomerOrderCreate(
            order_code=order_code,
            customer_id=payload.customer_id,
            status="OPEN",
            delivery_date=payload.requested_delivery_date,
            line=CustomerOrderLineCreate(
                line_code=line_code,
                product_id=payload.finished_product_id,
                quantity=payload.quantity,
                uom=payload.uom,
                status="OPEN",
            ),
        ),
    )
    repo = _repo(db, tenant)
    order_row = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, order_resp.order.customer_order_id
    )
    order_row.metadata_ = {
        **(order_row.metadata_ if isinstance(order_row.metadata_, dict) else {}),
        **metadata,
    }
    repo.db.commit()
    commitment = evaluate_delivery_commitment(
        db,
        tenant,
        finished_product_id=payload.finished_product_id,
        quantity=payload.quantity,
    )
    return AcCustomerSalesOrderCreateResponse(
        order=order_resp.order,
        line=order_resp.line,
        commitment=commitment,
    )


def _grade_from_product(product: Product) -> tuple[str, str]:
    code = product.product_code or "FG"
    label = product.product_name or code
    mesh = re.search(r"(\d+\s*x\s*\d+)", code, re.I)
    if mesh:
        grade = mesh.group(1).replace(" ", "").lower()
        return grade, f"{label} ({grade})"
    return code, label


def _screening_meta_by_lot(repo: TenantRepository) -> dict:
    out: dict = {}
    for ex in repo.query(OperationExecution).all():
        meta = ex.metadata_ if isinstance(ex.metadata_, dict) else {}
        if meta.get("process_step") != "SCREENING":
            continue
        out[ex.production_lot_id] = meta
    return out


def _lot_order_codes(repo: TenantRepository) -> tuple[dict, dict]:
    """Map production_order_id → order_code and order_line_id → order_code."""
    line_to_order: dict = {}
    po_by_id: dict = {}
    for order in repo.query(CustomerOrder).all():
        for line in repo.query(CustomerOrderLine).filter(
            CustomerOrderLine.order_id == order.customer_order_id
        ).all():
            line_to_order[line.order_line_id] = order.order_code
    for po in repo.query(ProductionOrder).all():
        po_by_id[po.production_order_id] = po
    po_to_order: dict = {}
    for po_id, po in po_by_id.items():
        po_to_order[po_id] = line_to_order.get(po.order_line_id)
    return po_by_id, po_to_order


def _stocked_lot_grade(
    product: Optional[Product],
    screening_meta: dict,
    lot: ProductionLot,
) -> tuple[str, str, Optional[str], Decimal]:
    mesh = str(screening_meta.get("mesh_size") or "").strip()
    good_kg = screening_meta.get("good_kg")
    qty = Decimal(str(good_kg if good_kg is not None else lot.lot_quantity or 0))
    if mesh:
        grade_code = mesh.replace(" ", "").lower()
        return grade_code, f"Mesh {mesh}", mesh, qty
    if product:
        grade_code, grade_label = _grade_from_product(product)
        return grade_code, grade_label, None, qty
    return "fg", "Finished goods", None, qty


def list_stocked_lots_for_dispatch(
    db: Session, tenant: TenantContext
) -> list[AcStockedLotOut]:
    ac_stock.reconcile_pending_stocked_lots(db, tenant)
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    po_by_id, po_to_order = _lot_order_codes(repo)
    screening_by_lot = _screening_meta_by_lot(repo)
    rows: list[AcStockedLotOut] = []

    lots = (
        repo.query(ProductionLot)
        .order_by(ProductionLot.created_at)
        .all()
    )
    for lot in lots:
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        st = (lot.status or "").upper()
        if st in ("DISPATCHED", "SCRAPPED", "CLOSED", "CANCELLED"):
            continue
        if st != "STOCKED" and not lot_meta.get("fg_stocked"):
            continue
        product_id = ac_stock._lot_finished_product_id(db, tenant, lot)
        product = products.get(product_id) if product_id else None
        screening = screening_by_lot.get(lot.production_lot_id, {})
        grade_code, grade_label, mesh, qty = _stocked_lot_grade(product, screening, lot)
        po = po_by_id.get(lot.production_order_id)
        rows.append(
            AcStockedLotOut(
                production_lot_id=lot.production_lot_id,
                lot_code=lot.lot_code,
                lot_quantity=qty,
                status=lot.status or "STOCKED",
                product_id=product_id,
                product_code=product.product_code if product else None,
                product_name=product.product_name if product else None,
                grade_code=grade_code,
                grade_label=grade_label,
                mesh_size=mesh,
                order_code=po_to_order.get(lot.production_order_id),
                production_order_code=po.production_order_code if po else None,
                stocked_at=lot_meta.get("stocked_at"),
            )
        )
    return rows


def list_grade_wise_stock(
    db: Session, tenant: TenantContext
) -> list[AcGradeStockOut]:
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    buckets: dict[str, AcGradeStockOut] = {}
    lot_counts: dict[str, int] = {}

    for row in list_stocked_lots_for_dispatch(db, tenant):
        key = (row.grade_code or row.product_code or "fg").upper()
        qty = Decimal(str(row.lot_quantity or 0))
        if qty <= 0:
            continue
        lot_counts[key] = lot_counts.get(key, 0) + 1
        existing = buckets.get(key)
        if existing:
            buckets[key] = existing.model_copy(
                update={
                    "quantity_kg": existing.quantity_kg + qty,
                    "stocked_lot_count": lot_counts[key],
                }
            )
        else:
            buckets[key] = AcGradeStockOut(
                grade_code=row.grade_code or key.lower(),
                grade_label=row.grade_label or row.product_code or key,
                product_id=row.product_id,
                product_code=row.product_code,
                quantity_kg=qty,
                uom="KG",
                source="stocked_lots",
                stocked_lot_count=1,
            )

    if buckets:
        return sorted(buckets.values(), key=lambda row: row.grade_code)

    for row in list_finished_goods_stock(db, tenant):
        product = products.get(row.product_id)
        grade_code, grade_label = (
            _grade_from_product(product)
            if product
            else (row.product_code, row.product_name or row.product_code)
        )
        key = grade_code.upper()
        qty = Decimal(str(row.quantity_kg or 0))
        buckets[key] = AcGradeStockOut(
            grade_code=grade_code,
            grade_label=grade_label,
            product_id=row.product_id,
            product_code=row.product_code,
            quantity_kg=qty,
            uom=row.uom or "KG",
            source="finished_goods",
            stocked_lot_count=0,
        )

    return sorted(buckets.values(), key=lambda row: row.grade_code)


def list_open_customer_sales_orders(
    db: Session, tenant: TenantContext
) -> list[AcOpenCustomerOrderOut]:
    repo = _repo(db, tenant)
    customers = {c.customer_id: c for c in repo.query(Customer).all()}
    products = {p.product_id: p for p in repo.query(Product).all()}
    rows: list[AcOpenCustomerOrderOut] = []

    for order in repo.query(CustomerOrder).order_by(CustomerOrder.created_at.desc()).all():
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        if meta.get("flow") != "CUSTOMER_SALES":
            continue
        dispatched = Decimal(str(meta.get("dispatched_kg") or 0))
        lines = (
            repo.query(CustomerOrderLine)
            .filter(CustomerOrderLine.order_id == order.customer_order_id)
            .all()
        )
        if not lines:
            continue
        line = lines[0]
        product = products.get(line.product_id)
        if not product:
            continue
        ordered = Decimal(str(meta.get("ordered_kg") or line.quantity or 0))
        remaining = max(ordered - dispatched, Decimal("0"))
        status = (order.status or "OPEN").upper()
        if status == "CLOSED" and remaining <= 0:
            continue
        stock = ac_stock.get_fg_stock_kg(db, tenant, line.product_id)
        customer = customers.get(order.customer_id) if order.customer_id else None
        delivery_raw = meta.get("delivery_date") or meta.get("requested_delivery_date")
        delivery_date = None
        if delivery_raw:
            try:
                delivery_date = date.fromisoformat(str(delivery_raw)[:10])
            except ValueError:
                delivery_date = None
        rows.append(
            AcOpenCustomerOrderOut(
                customer_order_id=order.customer_order_id,
                order_code=order.order_code,
                customer_id=order.customer_id,
                customer_code=customer.customer_code if customer else None,
                customer_name=customer.customer_name if customer else None,
                product_id=line.product_id,
                product_code=product.product_code,
                product_name=product.product_name,
                ordered_kg=ordered,
                dispatched_kg=dispatched,
                remaining_kg=remaining,
                stock_on_hand_kg=stock,
                can_dispatch_from_stock=stock >= remaining and remaining > 0,
                order_status=order.status,
                requested_delivery_date=delivery_date,
            )
        )
    return rows


def _stocked_lot_for_product(
    db: Session,
    tenant: TenantContext,
    product_id: UUID,
    *,
    lot_code: Optional[str] = None,
) -> ProductionLot:
    repo = _repo(db, tenant)
    lots = repo.query(ProductionLot).order_by(ProductionLot.created_at).all()
    for lot in lots:
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        st = (lot.status or "").upper()
        if st != "STOCKED" and not lot_meta.get("fg_stocked"):
            continue
        if lot_code and lot.lot_code != lot_code:
            continue
        lot_product = ac_stock._lot_finished_product_id(db, tenant, lot)
        if lot_product == product_id:
            return lot
    if lot_code:
        raise ValidationError(f"Stocked lot '{lot_code}' not found for this product grade")
    raise ValidationError(
        "No stocked lot available for this product — complete shop-floor execution first"
    )


def create_ac_dispatch_from_order(
    db: Session, tenant: TenantContext, payload: AcDispatchFromOrderCreate
) -> AcDispatchFromOrderResponse:
    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, payload.customer_order_id
    )
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    if meta.get("flow") != "CUSTOMER_SALES":
        raise ValidationError("Order is not a customer sales / purchase order")

    lines = (
        repo.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == order.customer_order_id)
        .all()
    )
    if not lines:
        raise ValidationError("Customer order has no line items")
    line = lines[0]
    product = repo.get_by_pk(Product, Product.product_id, line.product_id)
    grade_code, _ = _grade_from_product(product)

    ordered = Decimal(str(meta.get("ordered_kg") or line.quantity or 0))
    dispatched = Decimal(str(meta.get("dispatched_kg") or 0))
    remaining = max(ordered - dispatched, Decimal("0"))
    qty = Decimal(str(payload.quantity_kg))
    if qty > remaining:
        raise ValidationError(
            f"Dispatch quantity {qty} KG exceeds remaining PO quantity {remaining} KG"
        )

    stock = ac_stock.get_fg_stock_kg(db, tenant, line.product_id)
    if qty > stock:
        commitment = evaluate_delivery_commitment(
            db, tenant, finished_product_id=line.product_id, quantity=qty
        )
        raise ValidationError(
            f"Insufficient stock for {product.product_code}: "
            f"on hand {stock} KG, requested {qty} KG. {commitment.message}"
        )

    lot = _stocked_lot_for_product(
        db, tenant, line.product_id, lot_code=payload.lot_code
    )
    ac_stock.release_lot_schedule_resources(db, tenant, lot.production_lot_id)
    lot_qty = Decimal(str(lot.lot_quantity or 0))
    if qty > lot_qty:
        raise ValidationError(
            f"Lot {lot.lot_code} has only {lot_qty} KG; requested {qty} KG"
        )

    ac_stock.deduct_fg_stock_kg(db, tenant, line.product_id, qty)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    now_iso = datetime.now(timezone.utc).isoformat()
    if qty >= lot_qty:
        lot.status = "DISPATCHED"
        lot.metadata_ = {
            **lot_meta,
            "dispatched_at": now_iso,
            "fg_stocked": False,
            "fg_stock_kg_added": "0",
            "last_dispatch_kg": str(qty),
        }
    else:
        remaining_lot = lot_qty - qty
        lot.lot_quantity = remaining_lot
        lot.metadata_ = {
            **lot_meta,
            "fg_stock_kg_added": str(remaining_lot),
            "last_dispatch_kg": str(qty),
        }

    customer = (
        repo.get_by_pk(Customer, Customer.customer_id, order.customer_id)
        if order.customer_id
        else None
    )
    dispatch_code = resolve_ac_business_code(db, provided=None, entity="ac_dispatch")
    dispatch_meta = {
        "customer_id": customer.customer_code if customer else None,
        "order_id": order.order_code,
        "customer_order_id": str(order.customer_order_id),
        "grade_code": payload.grade_code or grade_code,
        "vehicle_number": payload.vehicle_number,
        "transporter_name": payload.transporter_name,
        "dispatch_status": "Shipped",
        "dispatch_date": datetime.now(timezone.utc).isoformat(),
        "remarks": payload.remarks,
        "lines": [
            {
                "lot_id": lot.lot_code,
                "part_id": product.product_code,
                "dispatch_quantity": str(qty),
                "accepted_quantity": str(qty),
                "rejected_quantity": "0",
            }
        ],
    }
    repo.add(
        QualityCheck(
            check_code=dispatch_code,
            production_lot_id=lot.production_lot_id,
            check_type="DISPATCH",
            status="Shipped",
            metadata_=dispatch_meta,
        )
    )

    dispatched += qty
    remaining_after = max(ordered - dispatched, Decimal("0"))
    order.status = "CLOSED" if remaining_after <= 0 else "PARTIAL"
    order.metadata_ = {
        **meta,
        "dispatched_kg": str(dispatched),
        "last_dispatch_id": dispatch_code,
        "last_dispatch_lot": lot.lot_code,
        "last_dispatch_kg": str(qty),
    }
    repo.db.commit()

    stock_after = ac_stock.get_fg_stock_kg(db, tenant, line.product_id)
    return AcDispatchFromOrderResponse(
        dispatch_id=dispatch_code,
        order_code=order.order_code,
        lot_code=lot.lot_code,
        grade_code=payload.grade_code or grade_code,
        quantity_kg=qty,
        remaining_on_order_kg=remaining_after,
        order_status=order.status or "OPEN",
        stock_on_hand_after_kg=stock_after,
    )


def create_make_to_stock_production_order(
    db: Session, tenant: TenantContext, payload: AcMakeToStockCreate
) -> AcMakeToStockCreateResponse:
    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)
    source_inward_id: Optional[UUID] = payload.inward_order_id

    if source_inward_id is not None:
        inward = repo.get_by_pk(
            CustomerOrder, CustomerOrder.customer_order_id, source_inward_id
        )
        inward = _require_raw_material_inward_order(db, tenant, inward)
        meta = inward.metadata_ if isinstance(inward.metadata_, dict) else {}

        release_qty = Decimal(str(payload.quantity))
        remaining = ac_stock.allocate_raw_from_inward(
            db, tenant, source_inward_id, release_qty
        )
        meta = {
            **meta,
            "last_release_kg": str(release_qty),
            "available_after_release_kg": str(remaining),
        }

        po_out = _ensure_production_order_for_inward(
            db,
            tenant,
            source_inward_id,
            quantity=release_qty,
            uom=payload.uom,
            production_order_code=payload.production_order_code,
            planned_quantity=release_qty,
        )
        po_row = repo.get_by_pk(
            ProductionOrder, ProductionOrder.production_order_id, po_out.production_order_id
        )
        po_row.metadata_ = {
            **(po_row.metadata_ if isinstance(po_row.metadata_, dict) else {}),
            "flow": "RELEASED_TO_PRODUCTION",
            "source_inward_order_id": str(source_inward_id),
            "last_release_kg": str(release_qty),
        }
        meta["production_order_id"] = str(po_row.production_order_id)
        meta["production_order_code"] = po_row.production_order_code
        inward.metadata_ = meta

        order_out = mes_core_entities._customer_order_out(db, tenant, inward)
        products = {p.product_id: p for p in repo.query(Product).all()}
        finished_line_out = None
        for line in order_out.lines or []:
            product = products.get(line.product_id)
            if product and not _is_raw_product(product):
                finished_line_out = line
                break
        if finished_line_out is None and order_out.lines:
            finished_line_out = order_out.lines[0]

        lot_code = resolve_ac_business_code(
            db, provided=None, entity="ac_production_lot"
        )
        lot_out = mes_core_entities.create_production_lot(
            db,
            tenant,
            ProductionLotCreate(
                lot_code=lot_code,
                production_order_id=po_out.production_order_id,
                lot_quantity=release_qty,
                status="CREATED",
            ),
        )
        repo.db.commit()
        return AcMakeToStockCreateResponse(
            order=order_out,
            line=finished_line_out,
            production_order=po_out,
            production_lot=lot_out,
        )

    finished: Product
    if payload.finished_product_id is not None:
        finished = repo.get_by_pk(
            Product, Product.product_id, payload.finished_product_id
        )
    else:
        raise ValidationError(
            "inward_order_id or finished_product_id is required for manufacturing"
        )

    order_resp = mes_core_entities.create_make_to_stock_order(
        db,
        tenant,
        order_code=None,
        source_inward_order_id=None,
        line=CustomerOrderLineCreate(
            line_code=None,
            product_id=finished.product_id,
            quantity=payload.quantity,
            uom=payload.uom,
            status="OPEN",
        ),
    )
    po_code = resolve_ac_business_code(
        db, provided=payload.production_order_code, entity="ac_production_order"
    )
    po_out = mes_core_entities.create_production_order(
        db,
        tenant,
        ProductionOrderCreate(
            production_order_code=po_code,
            order_line_id=order_resp.line.order_line_id,
            planned_quantity=payload.quantity,
            status="PLANNED",
        ),
    )
    po_row = repo.get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, po_out.production_order_id
    )
    po_row.metadata_ = {
        **(po_row.metadata_ if isinstance(po_row.metadata_, dict) else {}),
        "flow": "MAKE_TO_STOCK",
    }
    lot_code = resolve_ac_business_code(
        db, provided=None, entity="ac_production_lot"
    )
    lot_out = mes_core_entities.create_production_lot(
        db,
        tenant,
        ProductionLotCreate(
            lot_code=lot_code,
            production_order_id=po_out.production_order_id,
            lot_quantity=payload.quantity,
            status="CREATED",
        ),
    )
    repo.db.commit()
    return AcMakeToStockCreateResponse(
        order=order_resp.order,
        line=order_resp.line,
        production_order=po_out,
        production_lot=lot_out,
    )


def list_kiln_parameters(
    db: Session, tenant: TenantContext, lot_code: Optional[str] = None
) -> List[OperationExecutionOut]:
    rows = _repo(db, tenant).query(OperationExecution).order_by(OperationExecution.created_at.desc()).all()
    if lot_code:
        lot = _repo(db, tenant).get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
        rows = [r for r in rows if r.production_lot_id == lot.production_lot_id]
    return [OperationExecutionOut.model_validate(r) for r in rows]


def list_screening_executions(
    db: Session, tenant: TenantContext
) -> List[OperationExecutionOut]:
    rows = (
        _repo(db, tenant)
        .query(OperationExecution)
        .filter(OperationExecution.metadata_.contains({"process_step": "SCREENING"}))
        .order_by(OperationExecution.created_at.desc())
        .all()
    )
    if not rows:
        rows = _repo(db, tenant).query(OperationExecution).order_by(OperationExecution.created_at.desc()).limit(50).all()
    return [OperationExecutionOut.model_validate(r) for r in rows]


def list_quality_testing(
    db: Session, tenant: TenantContext
) -> List[QualityCheckOut]:
    return mes_core_entities.list_quality_checks(db, tenant)


def compute_yield_analysis(
    db: Session, tenant: TenantContext
) -> ActivatedCarbonYieldSummaryOut:
    """Plant yield = finished output kg ÷ raw material charged to production."""
    repo = _repo(db, tenant)
    lots = repo.query(ProductionLot).all()
    production_orders = repo.query(ProductionOrder).all()
    planned = sum(
        Decimal(str(o.planned_quantity or 0))
        for o in production_orders
    )
    lot_qty = sum(Decimal(str(l.lot_quantity or 0)) for l in lots)

    raw_status = _raw_material_status(db, tenant)
    raw_charged = Decimal(str(raw_status.charged_kg or 0))
    if raw_charged <= 0:
        for po in production_orders:
            po_meta = po.metadata_ if isinstance(po.metadata_, dict) else {}
            if po_meta.get("source_inward_order_id") or po_meta.get("flow") == "RELEASED_TO_PRODUCTION":
                raw_charged += Decimal(
                    str(po_meta.get("last_release_kg") or po.planned_quantity or 0)
                )
    if raw_charged <= 0 and planned > 0:
        raw_charged = planned

    fg_output = Decimal("0")
    for lot in lots:
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        st = (lot.status or "").upper()
        if st == "STOCKED":
            fg_output += Decimal(str(lot.lot_quantity or lot_meta.get("fg_stock_kg_added") or 0))
        elif st == "DISPATCHED":
            fg_output += Decimal(str(lot_meta.get("last_dispatch_kg") or 0))

    if fg_output <= 0:
        for row in list_finished_goods_stock(db, tenant):
            fg_output += Decimal(str(row.quantity_kg or 0))
        _, dispatched_total, _ = _dispatch_dashboard_summary(db, tenant)
        fg_output += dispatched_total

    avg_yield: Optional[Decimal] = None
    if raw_charged > 0 and fg_output > 0:
        avg_yield = (fg_output / raw_charged * Decimal("100")).quantize(Decimal("0.01"))
    elif raw_charged > 0 and lot_qty > 0:
        # WIP only — no fake yield until material is stocked or dispatched.
        avg_yield = None

    return ActivatedCarbonYieldSummaryOut(
        lot_count=len(lots),
        total_planned_quantity=planned,
        total_lot_quantity=lot_qty,
        average_yield_pct=avg_yield,
        industry_template_code=tenant.industry_template_code,
    )


def get_lot_traceability(
    db: Session, tenant: TenantContext, lot_code: str
) -> TraceabilityResponse:
    return mes_core_traceability.get_traceability(db, tenant, lot_code)


def list_knowledge_graph_triples(
    db: Session, tenant: TenantContext, limit: int = 100
) -> List[TripleOut]:
    rows = (
        _repo(db, tenant)
        .query(TripleStoreStaging)
        .order_by(TripleStoreStaging.created_at.desc())
        .limit(limit)
        .all()
    )
    return [TripleOut.model_validate(r) for r in rows]


def get_masters(db: Session, tenant: TenantContext) -> AcMastersOut:
    customers = mes_core_entities.list_customers(db, tenant)
    suppliers = mes_core_entities.list_suppliers(db, tenant)
    products = mes_core_entities.list_products(db, tenant)
    raw_material_types = ac_raw_material_types.list_raw_material_types(db, tenant)
    raw_products = [
        p
        for p in products
        if (p.product_type or "").upper() == "RAW_MATERIAL"
        or (p.product_code or "").upper().startswith("RAW-")
    ]
    if not raw_products:
        raw_products = products
    finished_products = [
        p
        for p in products
        if (p.product_code or "").upper() == FINISHED_PRODUCT_CODE
        or (p.product_type or "").upper() in ("FINISHED", "FINISHED_GOOD", "FG")
    ]
    if not finished_products:
        routable = _routable_product_ids(_repo(db, tenant))
        finished_products = [p for p in products if p.product_id in routable]
    production_orders = _production_orders_with_routing(db, tenant)
    production_lots = mes_core_entities.list_production_lots(db, tenant)
    kiln_rows = _list_tenant_kiln_resources(db, tenant)
    repo = _repo(db, tenant)
    all_resource_rows = repo.query(Resource).order_by(Resource.resource_code).all()
    machine_rows = [
        _resource_out(r)
        for r in all_resource_rows
        if (r.resource_type or "").upper() == "MACHINE"
        and not (r.resource_code or "").upper().startswith("RES-KILN")
    ]
    tool_rows = [
        _resource_out(r) for r in all_resource_rows if (r.resource_type or "").upper() == "TOOL"
    ]
    labor_rows = [
        _resource_out(r) for r in all_resource_rows if (r.resource_type or "").upper() == "LABOR"
    ]
    equipment_rows = mes_core_entities.list_equipment(db, tenant)

    return AcMastersOut(
        customers=customers,
        suppliers=suppliers,
        raw_products=raw_products,
        raw_material_types=raw_material_types,
        finished_products=finished_products,
        production_orders=production_orders,
        production_lots=production_lots,
        kilns=[_resource_out(r) for r in kiln_rows],
        machines=machine_rows,
        tools=tool_rows,
        labor_pools=labor_rows,
        equipment=equipment_rows,
        kiln_parameter_definitions=list_kiln_parameter_definitions(db, tenant),
        routing_master=_routing_master_summary(db, tenant),
    )


def _next_tenant_code_index(
    db: Session,
    tenant: TenantContext,
    *,
    model,
    code_column,
    prefix: str,
) -> int:
    rows = (
        db.query(model)
        .filter(model.tenant_id == tenant.tenant_id)
        .filter(code_column.like(f"{prefix}%"))
        .all()
    )
    max_n = 0
    for row in rows:
        code = getattr(row, code_column.key, None) or ""
        match = re.search(r"(\d+)$", str(code))
        if match:
            max_n = max(max_n, int(match.group(1)))
    return max_n + 1


def _next_kiln_index(db: Session, tenant: TenantContext, *, prefix: str = "RES-KILN-") -> int:
    return _next_tenant_code_index(
        db, tenant, model=Resource, code_column=Resource.resource_code, prefix=prefix
    )


_PLANT_RESOURCE_PREFIXES: dict[str, tuple[str, Optional[str]]] = {
    "MACHINE": ("RES-MACH-", "EQ-MACH-"),
    "TOOL": ("RES-TOOL-", None),
    "LABOR": ("RES-LAB-", None),
}


def _code_numeric_suffix(code: str, fallback_index: int) -> str:
    match = re.search(r"(\d+)$", code or "")
    if match:
        return match.group(1).zfill(AC_ID_PAD_WIDTH)
    return f"{fallback_index:0{AC_ID_PAD_WIDTH}d}"


def create_plant_resource(
    db: Session, tenant: TenantContext, payload: ResourceCreate
) -> AcPlantResourceOut:
    """Register tool, labor pool, or machine with optional linked equipment."""
    repo = _repo(db, tenant)
    name = payload.resource_name.strip()
    if not name:
        raise ValidationError("Resource name is required")

    rtype = (payload.resource_type or "MACHINE").upper()
    prefixes = _PLANT_RESOURCE_PREFIXES.get(rtype)
    if not prefixes:
        raise ValidationError(
            f"Unsupported resource type '{payload.resource_type}'. "
            "Use MACHINE, TOOL, or LABOR."
        )
    res_prefix, eq_prefix = prefixes

    resource_code = (payload.resource_code or "").strip()
    if not resource_code:
        idx = _next_tenant_code_index(
            db, tenant, model=Resource, code_column=Resource.resource_code, prefix=res_prefix
        )
        resource_code = f"{res_prefix}{idx:0{AC_ID_PAD_WIDTH}d}"

    if (
        _tenant_resources(db, tenant)
        .filter(Resource.resource_code == resource_code)
        .first()
    ):
        raise ValidationError(
            f"Resource '{resource_code}' already exists. "
            "Leave the code blank to auto-assign the next available code."
        )

    meta: dict = {"role": rtype.lower()}
    if rtype == "LABOR" and payload.headcount is not None:
        meta["headcount"] = int(payload.headcount)
        meta["operators"] = int(payload.headcount)

    resource = repo.add(
        Resource(
            resource_code=resource_code,
            resource_name=name,
            resource_type=rtype,
            status=payload.status or "ACTIVE",
            metadata_=meta,
        )
    )
    repo.db.flush()

    equipment_id = None
    equipment_code = None
    equipment_name = None
    if rtype == "MACHINE" and eq_prefix:
        idx = _next_tenant_code_index(
            db, tenant, model=Equipment, code_column=Equipment.equipment_code, prefix=eq_prefix
        )
        suffix = _code_numeric_suffix(resource_code, idx)
        equipment_code = f"{eq_prefix}{suffix}"
        if (
            _tenant_equipment(db, tenant)
            .filter(Equipment.equipment_code == equipment_code)
            .first()
        ):
            equipment_code = f"{eq_prefix}{idx:0{AC_ID_PAD_WIDTH}d}"
        equipment = repo.add(
            Equipment(
                equipment_code=equipment_code,
                equipment_name=name,
                resource_id=resource.resource_id,
                equipment_type="MACHINE",
                status=payload.status or "ACTIVE",
            )
        )
        repo.db.flush()
        equipment_id = equipment.equipment_id
        equipment_name = equipment.equipment_name

    repo.commit_refresh(resource)

    return AcPlantResourceOut(
        resource_id=resource.resource_id,
        resource_code=resource.resource_code,
        resource_name=resource.resource_name,
        resource_type=resource.resource_type,
        status=resource.status,
        headcount=_headcount_from_metadata(resource.metadata_)
        if rtype == "LABOR"
        else None,
        equipment_id=equipment_id,
        equipment_code=equipment_code,
        equipment_name=equipment_name,
    )


def create_kiln(db: Session, tenant: TenantContext, payload: AcKilnCreate) -> AcKilnOut:
    """Register an activation kiln (machine resource + linked equipment)."""
    repo = _repo(db, tenant)
    name = payload.kiln_name.strip()
    if not name:
        raise ValidationError("Kiln name is required")

    idx = _next_kiln_index(db, tenant)
    resource_code = f"RES-KILN-{idx:0{AC_ID_PAD_WIDTH}d}"
    equipment_code = f"EQ-KILN-{idx:0{AC_ID_PAD_WIDTH}d}"

    if (
        _tenant_resources(db, tenant)
        .filter(Resource.resource_code == resource_code)
        .first()
    ):
        raise ValidationError(
            f"Resource '{resource_code}' already exists for this plant. "
            "Leave Resource code blank to auto-assign the next RES-KILN-* code."
        )
    if (
        _tenant_equipment(db, tenant)
        .filter(Equipment.equipment_code == equipment_code)
        .first()
    ):
        raise ValidationError(
            f"Equipment '{equipment_code}' already exists for this plant. "
            "Leave Equipment code blank to auto-assign the next EQ-KILN-* code."
        )

    resource = repo.add(
        Resource(
            resource_code=resource_code,
            resource_name=name,
            resource_type="MACHINE",
            status=payload.status or "ACTIVE",
            metadata_={"role": "kiln", "equipment_class": "KILN"},
        )
    )
    repo.db.flush()

    equipment = repo.add(
        Equipment(
            equipment_code=equipment_code,
            equipment_name=name,
            resource_id=resource.resource_id,
            equipment_type="KILN",
            status=payload.status or "ACTIVE",
        )
    )
    repo.commit_refresh(resource)
    repo.db.refresh(equipment)

    return AcKilnOut(
        resource_id=resource.resource_id,
        resource_code=resource.resource_code,
        resource_name=resource.resource_name,
        equipment_id=equipment.equipment_id,
        equipment_code=equipment.equipment_code,
        equipment_name=equipment.equipment_name,
        status=resource.status,
    )


def _is_raw_product(product: Product) -> bool:
    code = (product.product_code or "").upper()
    ptype = (product.product_type or "").upper()
    return ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-")


def _raw_material_status(db: Session, tenant: TenantContext) -> AcRawMaterialStatusOut:
    """Raw material mass balance for dashboard KPIs (inward → released to production)."""
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    ordered = Decimal("0")
    allocated = Decimal("0")
    raw_inward_order_ids: set = set()

    for order in repo.query(CustomerOrder).all():
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        lines = (
            repo.query(CustomerOrderLine)
            .filter(CustomerOrderLine.order_id == order.customer_order_id)
            .all()
        )
        raw_qty = Decimal("0")
        is_inward = meta.get("flow") == "RAW_MATERIAL_INWARD"
        for line in lines:
            product = products.get(line.product_id)
            if product and _is_raw_product(product):
                raw_qty += Decimal(str(line.quantity or 0))
                is_inward = True
        if not is_inward or raw_qty <= 0:
            continue
        raw_inward_order_ids.add(order.customer_order_id)
        ordered += raw_qty
        allocated += Decimal(str(meta.get("allocated_to_production_kg") or 0))

    charged = allocated
    pending = max(Decimal("0"), ordered - allocated)
    return AcRawMaterialStatusOut(
        ordered_kg=ordered,
        charged_kg=charged,
        pending_kg=pending,
        open_order_count=len(raw_inward_order_ids),
    )


def _kiln_status_rows(db: Session, tenant: TenantContext) -> list[AcKilnStatusOut]:
    repo = _repo(db, tenant)
    kiln_rows = _list_tenant_kiln_resources(db, tenant)
    executions = (
        repo.query(OperationExecution)
        .order_by(OperationExecution.created_at.desc())
        .all()
    )
    lots_by_id = {l.production_lot_id: l for l in repo.query(ProductionLot).all()}
    rows: list[AcKilnStatusOut] = []
    for kiln in kiln_rows:
        code = kiln.resource_code
        latest = None
        for ex in executions:
            meta = ex.metadata_ or {}
            if meta.get("kiln_resource_code") == code or meta.get("resource_code") == code:
                latest = ex
                break
        lot = lots_by_id.get(latest.production_lot_id) if latest else None
        if lot is None:
            for candidate in lots_by_id.values():
                if (candidate.status or "").upper() != "IN_PROGRESS":
                    continue
                for ex in executions:
                    if ex.production_lot_id != candidate.production_lot_id:
                        continue
                    meta = ex.metadata_ or {}
                    if meta.get("kiln_resource_code") == code or meta.get("resource_code") == code:
                        lot = candidate
                        latest = ex
                        break
                if lot:
                    break
        status = "IDLE"
        if lot and latest:
            lot_status = (lot.status or "").upper()
            ex_status = (latest.status or "").upper()
            if lot_status == "IN_PROGRESS" and ex_status not in ("COMPLETED", "CLOSED"):
                status = "RUNNING"
            elif lot_status in {"IN_PROGRESS", "COMPLETED", "QC_PENDING"} and ex_status == "COMPLETED":
                status = "COOLING"
        rows.append(
            AcKilnStatusOut(
                resource_code=code,
                resource_name=kiln.resource_name or code,
                status=status,
                active_lot_code=lot.lot_code if lot else None,
                active_lot_kg=lot.lot_quantity if lot else None,
                last_reading_at=latest.created_at if latest else None,
            )
        )
    return rows


def _latest_feasibility_by_lot(db: Session, tenant: TenantContext) -> dict:
    repo = _repo(db, tenant)
    rows = (
        repo.query(FeasibilityCheck)
        .order_by(FeasibilityCheck.created_at.desc())
        .all()
    )
    latest: dict = {}
    for row in rows:
        lot_id = row.production_lot_id
        if lot_id not in latest:
            latest[lot_id] = row.overall_status
    return latest


_TERMINAL_LOT_STATUSES = frozenset({"DISPATCHED", "CLOSED", "CANCELLED"})
_OPEN_LOT_STATUSES = frozenset(
    {"COMPLETED", "QC_PENDING", "STOCKED", "DISPATCHED", "CLOSED", "CANCELLED"}
)


def _shop_floor_execution_counts(repo: TenantRepository) -> dict:
    """Map production_lot_id -> (completed_ops, total_schedule_ops)."""
    counts: dict = {}
    for row in repo.query(OperationExecution).all():
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if not (meta.get("is_production_schedule") or meta.get("schedule_code")):
            continue
        lid = row.production_lot_id
        done, total = counts.get(lid, (0, 0))
        total += 1
        if (row.status or "").upper() == "COMPLETED":
            done += 1
        counts[lid] = (done, total)
    return counts


def _lot_pipeline_stage(
    lot_status: Optional[str],
    feasibility_status: Optional[str],
    *,
    exec_done: int = 0,
    exec_total: int = 0,
) -> str:
    st = (lot_status or "").upper()
    if st == "DISPATCHED":
        return "Dispatched"
    if st in ("CLOSED", "CANCELLED"):
        return "Closed"
    if st == "STOCKED":
        return "Finished goods stock"
    if st == "QC_PENDING":
        return "Quality testing"
    if st == "COMPLETED":
        return "Shop-floor complete"
    if st == "IN_PROGRESS":
        if exec_total > 0 and exec_done < exec_total:
            return f"Execution ({exec_done}/{exec_total})"
        if exec_total > 0 and exec_done >= exec_total:
            return "Execution complete"
        feas = (feasibility_status or "").upper()
        if feas in ("READY", "OK", "PASSED"):
            return "Routing / execution"
        return "Kiln feed"
    if st == "CREATED":
        return "Awaiting feasibility"
    return lot_status or "Unknown"


def _lot_line_rows(db: Session, tenant: TenantContext) -> list[AcLotLineOut]:
    repo = _repo(db, tenant)
    orders = repo.query(CustomerOrder).all()
    line_to_order: dict = {}
    for order in orders:
        for line in repo.query(CustomerOrderLine).filter(
            CustomerOrderLine.order_id == order.customer_order_id
        ).all():
            line_to_order[line.order_line_id] = order.order_code

    po_rows = repo.query(ProductionOrder).all()
    po_by_id = {po.production_order_id: po for po in po_rows}
    feas_by_lot = _latest_feasibility_by_lot(db, tenant)
    exec_counts = _shop_floor_execution_counts(repo)

    lots = (
        repo.query(ProductionLot)
        .order_by(ProductionLot.created_at.desc())
        .all()
    )
    rows: list[AcLotLineOut] = []
    for lot in lots:
        po = po_by_id.get(lot.production_order_id)
        order_code = line_to_order.get(po.order_line_id) if po else None
        done, total = exec_counts.get(lot.production_lot_id, (0, 0))
        feas = feas_by_lot.get(lot.production_lot_id)
        stage = _lot_pipeline_stage(
            lot.status, feas, exec_done=done, exec_total=total
        )
        in_progress = (lot.status or "").upper() not in _TERMINAL_LOT_STATUSES
        rows.append(
            AcLotLineOut(
                order_code=order_code,
                production_order_code=po.production_order_code if po else None,
                lot_code=lot.lot_code,
                lot_quantity=lot.lot_quantity,
                status=lot.status,
                feasibility_status=feas,
                pipeline_stage=stage,
                is_in_progress=in_progress,
            )
        )
    return rows


def list_open_production_lots(
    db: Session, tenant: TenantContext, *, include_routing_complete: bool = False
) -> list[AcOpenLotOut]:
    """Lots eligible for feasibility, kiln feed, and routing (server-side filter)."""
    repo = _repo(db, tenant)
    orders = repo.query(CustomerOrder).all()
    line_to_order: dict = {}
    for order in orders:
        for line in repo.query(CustomerOrderLine).filter(
            CustomerOrderLine.order_id == order.customer_order_id
        ).all():
            line_to_order[line.order_line_id] = order.order_code

    po_rows = repo.query(ProductionOrder).all()
    po_by_id = {po.production_order_id: po for po in po_rows}
    feas_by_lot = _latest_feasibility_by_lot(db, tenant)
    exec_counts = _shop_floor_execution_counts(repo)

    lots = (
        repo.query(ProductionLot)
        .order_by(ProductionLot.created_at.desc())
        .all()
    )
    rows: list[AcOpenLotOut] = []
    for lot in lots:
        st = (lot.status or "").upper()
        done, total = exec_counts.get(lot.production_lot_id, (0, 0))
        routing_complete = total > 0 and done >= total
        if st in _OPEN_LOT_STATUSES:
            continue
        if routing_complete and not include_routing_complete:
            continue

        po = po_by_id.get(lot.production_order_id)
        order_code = line_to_order.get(po.order_line_id) if po else None
        feas = feas_by_lot.get(lot.production_lot_id)
        stage = _lot_pipeline_stage(
            lot.status, feas, exec_done=done, exec_total=total
        )
        rows.append(
            AcOpenLotOut(
                production_lot_id=lot.production_lot_id,
                order_code=order_code,
                production_order_code=po.production_order_code if po else None,
                lot_code=lot.lot_code,
                lot_quantity=lot.lot_quantity,
                status=lot.status,
                feasibility_status=feas,
                pipeline_stage=stage,
                routing_complete=routing_complete,
            )
        )
    return rows


def _active_orders_from_lot_lines(
    lot_lines: list[AcLotLineOut],
) -> list[AcActiveOrderOut]:
    priority = {
        "Execution": 0,
        "Kiln feed": 1,
        "Routing / execution": 2,
        "Quality testing": 3,
        "Finished goods stock": 4,
        "Awaiting feasibility": 5,
    }

    active: list[AcActiveOrderOut] = []
    for row in lot_lines:
        if not row.is_in_progress:
            continue
        stage = row.pipeline_stage or "In progress"
        active.append(
            AcActiveOrderOut(
                lot_code=row.lot_code,
                production_order_code=row.production_order_code,
                order_code=row.order_code,
                lot_quantity=row.lot_quantity,
                lot_status=row.status,
                pipeline_stage=stage,
                feasibility_status=row.feasibility_status,
            )
        )

    def sort_key(item: AcActiveOrderOut) -> tuple:
        stage = item.pipeline_stage or ""
        for prefix, rank in priority.items():
            if stage.startswith(prefix) or stage == prefix:
                return (rank, item.lot_code)
        return (99, item.lot_code)

    active.sort(key=sort_key)
    return active


def _process_step_rows(db: Session, tenant: TenantContext) -> list[AcProcessStepOut]:
    repo = _repo(db, tenant)
    exec_counts = _shop_floor_execution_counts(repo)
    inward_count = sum(
        1
        for order in repo.query(CustomerOrder).all()
        if isinstance(order.metadata_, dict)
        and order.metadata_.get("flow") == "RAW_MATERIAL_INWARD"
    )
    lot_rows = repo.query(ProductionLot).all()
    kiln_feed_count = sum(
        1 for lot in lot_rows if (lot.status or "").upper() == "IN_PROGRESS"
    )
    routing_lot_count = sum(
        1 for lot in lot_rows if exec_counts.get(lot.production_lot_id, (0, 0))[1] > 0
    )
    stocked_count = sum(
        1 for lot in lot_rows if (lot.status or "").upper() == "STOCKED"
    )
    feasibility_count = repo.query(FeasibilityCheck).count()
    execution_count = sum(
        1
        for ex in repo.query(OperationExecution).all()
        if (ex.metadata_ or {}).get("is_production_schedule")
        or (ex.metadata_ or {}).get("schedule_code")
    )
    activation_count = (
        repo.query(OperationExecution)
        .filter(OperationExecution.metadata_.contains({"process_step": "ACTIVATION"}))
        .count()
    )
    screening_count = (
        repo.query(OperationExecution)
        .filter(OperationExecution.metadata_.contains({"process_step": "SCREENING"}))
        .count()
    )
    qc_count = (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type != "DISPATCH")
        .count()
    )
    dispatch_count = len(mes_core_dispatch.list_dispatches(db, tenant))
    counts = {
        "AC_RAW_MATERIAL_INWARD": inward_count,
        "AC_RAW_MATERIAL_QC": sum(
            1
            for order in repo.query(CustomerOrder).all()
            if isinstance(order.metadata_, dict)
            and isinstance(order.metadata_.get("raw_material_qc"), dict)
            and order.metadata_["raw_material_qc"].get("qc_status") not in (None, "", "PENDING")
        ),
        "AC_KILN_FEED": kiln_feed_count or routing_lot_count,
        "FEASIBILITY": feasibility_count,
        "EXECUTION": execution_count,
        "ROUTING": routing_lot_count,
        "AC_HOURLY_KILN_PARAMETERS": activation_count,
        "AC_SCREENING": screening_count,
        "AC_QUALITY_TESTING": qc_count,
        "AC_YIELD_ANALYSIS": len(lot_rows),
        "FG_STOCK": stocked_count,
        "DISPATCH": dispatch_count,
    }
    caps = set(tenant.enabled_capabilities or [])
    steps: list[AcProcessStepOut] = []
    for step_order, label, path, cap in AC_PROCESS_FLOW:
        if cap and cap not in caps:
            continue
        count_key = cap or AC_PROCESS_COUNT_KEYS.get(path, "DISPATCH")
        count = counts.get(count_key, 0)
        if count <= 0:
            status = "pending"
        elif count_key == "DISPATCH" and count > 0:
            status = "complete"
        elif count_key in {"FEASIBILITY", "EXECUTION", "ROUTING"} and count > 0:
            status = "done" if count_key in {"FEASIBILITY", "ROUTING"} else "active"
        else:
            status = "active"
        steps.append(
            AcProcessStepOut(
                step_order=step_order,
                label=label,
                path=path,
                capability_code=cap,
                record_count=count,
                status=status,
            )
        )
    return steps


def _dispatch_dashboard_summary(
    db: Session, tenant: TenantContext
) -> tuple[int, Decimal, list[AcRecentDispatchOut]]:
    repo = _repo(db, tenant)
    lots = {lot.production_lot_id: lot for lot in repo.query(ProductionLot).all()}
    rows = (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type == "DISPATCH")
        .order_by(QualityCheck.created_at.desc())
        .all()
    )
    total_kg = Decimal("0")
    recent: list[AcRecentDispatchOut] = []
    for row in rows:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        line_qty = Decimal("0")
        for line in meta.get("lines") or []:
            if isinstance(line, dict):
                line_qty += Decimal(str(line.get("dispatch_quantity") or 0))
        if line_qty <= 0:
            line_qty = Decimal(str(meta.get("last_dispatch_kg") or 0))
        total_kg += line_qty
        if len(recent) < 8:
            lot = lots.get(row.production_lot_id)
            dispatch_dt = meta.get("dispatch_date")
            parsed_dt = None
            if dispatch_dt:
                try:
                    parsed_dt = datetime.fromisoformat(str(dispatch_dt).replace("Z", "+00:00"))
                except ValueError:
                    parsed_dt = row.created_at
            recent.append(
                AcRecentDispatchOut(
                    dispatch_id=row.check_code,
                    order_code=meta.get("order_id"),
                    lot_code=lot.lot_code if lot else None,
                    quantity_kg=line_qty,
                    dispatch_date=parsed_dt or row.created_at,
                    customer_code=meta.get("customer_id"),
                    vehicle_number=meta.get("vehicle_number"),
                )
            )
    return len(rows), total_kg, recent


def get_dashboard_summary(db: Session, tenant: TenantContext) -> AcDashboardOut:
    yield_summary = compute_yield_analysis(db, tenant)
    raw_material = _raw_material_status(db, tenant)
    kilns = _kiln_status_rows(db, tenant)
    process_steps = _process_step_rows(db, tenant)
    lot_lines = _lot_line_rows(db, tenant)
    active_orders = _active_orders_from_lot_lines(lot_lines)
    repo = _repo(db, tenant)
    qc_count = (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type != "DISPATCH")
        .count()
    )
    dispatch_count, dispatched_kg_total, recent_dispatches = _dispatch_dashboard_summary(
        db, tenant
    )
    fg_stock = list_finished_goods_stock(db, tenant)
    grade_stock = list_grade_wise_stock(db, tenant)
    grade_stock_total = sum(Decimal(str(row.quantity_kg or 0)) for row in grade_stock)
    product_stock_total = sum(
        Decimal(str(row.quantity_kg or 0)) for row in fg_stock
    )
    finished_goods_stock_kg = (
        grade_stock_total if grade_stock_total > 0 else product_stock_total
    )
    open_customer_orders = list_open_customer_sales_orders(db, tenant)
    return AcDashboardOut(
        yield_summary=yield_summary,
        raw_material=raw_material,
        kilns=kilns,
        process_steps=process_steps,
        lot_lines=lot_lines,
        active_orders=active_orders,
        quality_check_count=qc_count,
        dispatch_count=dispatch_count,
        dispatched_kg_total=dispatched_kg_total,
        finished_goods_stock_kg=finished_goods_stock_kg,
        grade_stock=grade_stock,
        open_customer_orders=open_customer_orders,
        recent_dispatches=recent_dispatches,
        kiln_parameter_definitions=list_kiln_parameter_definitions(db, tenant),
    )


def _routing_operation_for_lot(
    db: Session, tenant: TenantContext, production_lot_id, process_step: str
) -> RoutingOperation:
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, production_lot_id)
    po = repo.get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, lot.production_order_id
    )
    line = repo.get_by_pk(
        CustomerOrderLine, CustomerOrderLine.order_line_id, po.order_line_id
    )
    routing = (
        repo.query(Routing)
        .filter(Routing.product_id == line.product_id, Routing.is_active.is_(True))
        .order_by(Routing.routing_version.desc())
        .first()
    )
    if not routing:
        raise ValueError(f"No active routing for product on lot {lot.lot_code}")

    ops = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    target_code = f"OP-{process_step}"
    for op in ops:
        meta = op.metadata_ or {}
        if meta.get("process_step") == process_step or op.operation_code == target_code:
            return op
    raise ValueError(f"No routing operation for process step {process_step}")


def _create_process_execution(
    db: Session,
    tenant: TenantContext,
    production_lot_id,
    process_step: str,
    metadata: dict,
) -> OperationExecutionOut:
    repo = _repo(db, tenant)
    op = _routing_operation_for_lot(db, tenant, production_lot_id, process_step)
    code = resolve_ac_business_code(db, provided=None, entity="ac_operation_execution")
    row = repo.add(
        OperationExecution(
            execution_code=code,
            production_lot_id=production_lot_id,
            routing_operation_id=op.routing_operation_id,
            status="COMPLETED",
            metadata_={
                **metadata,
                "process_step": process_step,
                "industry_template_code": tenant.industry_template_code,
            },
        )
    )
    return OperationExecutionOut.model_validate(repo.commit_refresh(row))


def _ensure_production_order_for_inward(
    db: Session,
    tenant: TenantContext,
    order_id,
    *,
    quantity,
    uom: str = "KG",
    production_order_code: Optional[str] = None,
    planned_quantity: Optional[Decimal] = None,
) -> ProductionOrderOut:
    """Ensure finished-product line + production order exist for a raw material inward order."""
    repo = _repo(db, tenant)
    finished = _resolve_finished_product(repo)
    products = {p.product_id: p for p in repo.query(Product).all()}
    lines = (
        repo.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == order_id)
        .all()
    )
    finished_line = None
    raw_line = None
    for line in lines:
        product = products.get(line.product_id)
        if not product:
            continue
        if _is_raw_product(product):
            raw_line = line
        elif (product.product_code or "").upper() == FINISHED_PRODUCT_CODE:
            finished_line = line

    line_qty = raw_line.quantity if raw_line else quantity
    line_uom = raw_line.uom if raw_line else uom
    po_qty = planned_quantity if planned_quantity is not None else line_qty

    if finished_line is None:
        prod_line_code = resolve_ac_business_code(
            db, provided=None, entity="ac_customer_order_line"
        )
        finished_line_out = mes_core_entities.create_customer_order_line(
            db,
            tenant,
            order_id,
            CustomerOrderLineCreate(
                line_code=prod_line_code,
                product_id=finished.product_id,
                quantity=po_qty,
                uom=line_uom,
                status="OPEN",
            ),
        )
        finished_line_id = finished_line_out.order_line_id
    else:
        finished_line_id = finished_line.order_line_id
        if Decimal(str(finished_line.quantity)) != po_qty:
            finished_line.quantity = po_qty
            repo.db.flush()

    existing_po = (
        repo.query(ProductionOrder)
        .filter(ProductionOrder.order_line_id == finished_line_id)
        .first()
    )
    if existing_po:
        po_meta = (
            existing_po.metadata_ if isinstance(existing_po.metadata_, dict) else {}
        )
        source_inward = po_meta.get("source_inward_order_id")
        if source_inward and str(source_inward) != str(order_id):
            existing_po = None
    if existing_po:
        existing_lot_total = sum(
            Decimal(str(row.lot_quantity or 0))
            for row in repo.query(ProductionLot)
            .filter(ProductionLot.production_order_id == existing_po.production_order_id)
            .all()
        )
        existing_po.planned_quantity = existing_lot_total + po_qty
        po_meta = (
            existing_po.metadata_ if isinstance(existing_po.metadata_, dict) else {}
        )
        existing_po.metadata_ = {
            **po_meta,
            "source_inward_order_id": str(order_id),
            "last_release_kg": str(po_qty),
        }
        existing_po.status = "PLANNED"
        repo.db.flush()
        return mes_core_entities.get_production_order(
            db, tenant, existing_po.production_order_id
        )

    po_code = resolve_ac_business_code(
        db, provided=production_order_code, entity="ac_production_order"
    )
    return mes_core_entities.create_production_order(
        db,
        tenant,
        ProductionOrderCreate(
            production_order_code=po_code,
            order_line_id=finished_line_id,
            planned_quantity=po_qty,
            status="PLANNED",
        ),
    )


def backfill_inward_production_orders(
    db: Session, tenant: TenantContext
) -> List[dict]:
    """Create missing production orders for existing raw material inward customer orders."""
    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    rows = repo.query(CustomerOrder).order_by(CustomerOrder.created_at).all()
    created: List[dict] = []
    for order in rows:
        order_out = mes_core_entities._customer_order_out(db, tenant, order)
        if not _order_is_raw_material_inward(order, order_out, products):
            continue
        raw_qty = None
        raw_uom = "KG"
        for line in order_out.lines or []:
            product = products.get(line.product_id)
            if product and _is_raw_product(product):
                raw_qty = line.quantity
                raw_uom = line.uom or "KG"
                break
        if raw_qty is None:
            continue
        po_before = (
            repo.query(ProductionOrder)
            .join(
                CustomerOrderLine,
                CustomerOrderLine.order_line_id == ProductionOrder.order_line_id,
            )
            .filter(CustomerOrderLine.order_id == order.customer_order_id)
            .first()
        )
        if po_before:
            continue
        po_out = _ensure_production_order_for_inward(
            db,
            tenant,
            order.customer_order_id,
            quantity=raw_qty,
            uom=raw_uom,
        )
        created.append(
            {
                "order_code": order.order_code,
                "production_order_code": po_out.production_order_code,
            }
        )
    return created


def create_raw_material_inward(
    db: Session, tenant: TenantContext, payload: AcRawMaterialInwardCreate
) -> AcRawMaterialInwardCreateResponse:
    sync_ac_sequences(db, tenant.tenant_id)
    order_code = resolve_ac_business_code(
        db, provided=payload.order_code, entity="ac_customer_order"
    )
    line_code = resolve_ac_business_code(
        db, provided=None, entity="ac_customer_order_line"
    )
    order_resp = mes_core_entities.create_inward_order(
        db,
        tenant,
        InwardOrderCreate(
            order_code=order_code,
            supplier_id=payload.supplier_id,
            status="OPEN",
            line=CustomerOrderLineCreate(
                line_code=line_code,
                product_id=payload.product_id,
                quantity=payload.quantity,
                uom=payload.uom,
                status="OPEN",
            ),
        ),
    )
    repo = _repo(db, tenant)
    order_row = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, order_resp.order.customer_order_id
    )
    order_row.metadata_ = {
        **(order_row.metadata_ if isinstance(order_row.metadata_, dict) else {}),
        "flow": "RAW_MATERIAL_INWARD",
        "raw_product_id": str(payload.product_id),
    }
    repo.db.commit()
    repo.db.refresh(order_row)
    po_out = None
    if payload.create_production_order:
        po_out = _ensure_production_order_for_inward(
            db,
            tenant,
            order_resp.order.customer_order_id,
            quantity=payload.quantity,
            uom=payload.uom,
            production_order_code=payload.production_order_code,
        )
    return AcRawMaterialInwardCreateResponse(
        order=order_resp.order,
        line=order_resp.line,
        production_order=po_out,
    )


def _raw_material_qc_from_order(
    db: Session, tenant: TenantContext, order: CustomerOrder
) -> Optional[AcRawMaterialQcOut]:
    repo = _repo(db, tenant)
    lines = (
        repo.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == order.customer_order_id)
        .all()
    )
    products = {p.product_id: p for p in repo.query(Product).all()}
    raw_line = None
    for line in lines:
        product = products.get(line.product_id)
        if product and _is_raw_product(product):
            raw_line = (line, product)
            break
    if not raw_line:
        return None

    line, product = raw_line
    meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
    qc = meta.get("raw_material_qc") if isinstance(meta.get("raw_material_qc"), dict) else {}

    return AcRawMaterialQcOut(
        customer_order_id=order.customer_order_id,
        order_code=order.order_code,
        product_code=product.product_code,
        product_name=product.product_name,
        quantity=line.quantity,
        uom=line.uom,
        moisture_pct=qc.get("moisture_pct"),
        ash_pct=qc.get("ash_pct"),
        foreign_matter_pct=qc.get("foreign_matter_pct"),
        stones_kg=qc.get("stones_kg"),
        unburnt_kg=qc.get("unburnt_kg"),
        minus20_kg=qc.get("minus20_kg"),
        operator_remarks=qc.get("operator_remarks"),
        qc_status=qc.get("qc_status") or "PENDING",
        qc_at=qc.get("qc_at"),
    )


def _stage_inward_qc_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    qc_payload: dict,
) -> None:
    """Materialize inward QC impurity capture into kg.triple_store_staging (triplet ontology)."""
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:tested_by",
            object_uri=f"urn:nyra:ac:rawMaterialQc:{order.order_code}",
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    literal_triples = (
        ("stones_kg", "urn:nyra:hasStonesKg"),
        ("unburnt_kg", "urn:nyra:hasUnburntKg"),
        ("minus20_kg", "urn:nyra:hasMinus20Kg"),
    )
    for field, predicate in literal_triples:
        value = qc_payload.get(field)
        if value is None:
            continue
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri=predicate,
                object_literal=str(value),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )
    for field, param_uri in (
        ("moisture_pct", "urn:nyra:ac:parameter:MOISTURE_PCT"),
        ("ash_pct", "urn:nyra:ac:parameter:ASH_PCT"),
        ("foreign_matter_pct", "urn:nyra:ac:parameter:FOREIGN_MATTER_PCT"),
    ):
        value = qc_payload.get(field)
        if value is None:
            continue
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=param_uri,
                object_literal=str(value),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )


def list_raw_material_qc(
    db: Session, tenant: TenantContext
) -> List[AcRawMaterialQcOut]:
    repo = _repo(db, tenant)
    orders = repo.query(CustomerOrder).order_by(CustomerOrder.created_at.desc()).all()
    rows: list[AcRawMaterialQcOut] = []
    for order in orders:
        row = _raw_material_qc_from_order(db, tenant, order)
        if row:
            rows.append(row)
    return rows


def create_raw_material_qc(
    db: Session, tenant: TenantContext, payload: AcRawMaterialQcCreate
) -> AcRawMaterialQcOut:
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, payload.customer_order_id
    )
    existing = _raw_material_qc_from_order(db, tenant, order)
    if not existing:
        raise NotFoundError(
            f"Order '{order.order_code}' has no raw material line for QC"
        )
    prior_status = str(existing.qc_status or "PENDING").upper()
    if ac_stock.qc_status_passed(prior_status) or prior_status in (
        "FAIL",
        "QC_FAILED",
        "REJECTED",
    ):
        raise ValidationError(
            f"Order '{order.order_code}' already has QC status {prior_status} — "
            "select a pending inward order instead."
        )

    meta = dict(order.metadata_ if isinstance(order.metadata_, dict) else {})

    def _json_val(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    qc_payload = {
        k: _json_val(v)
        for k, v in {
            "moisture_pct": payload.moisture_pct,
            "ash_pct": payload.ash_pct,
            "foreign_matter_pct": payload.foreign_matter_pct,
            "stones_kg": payload.stones_kg,
            "unburnt_kg": payload.unburnt_kg,
            "minus20_kg": payload.minus20_kg,
            "operator_remarks": payload.operator_remarks,
            "qc_status": (payload.qc_status or "PASS").upper(),
            "qc_at": datetime.now(timezone.utc).isoformat(),
        }.items()
        if v is not None
    }
    meta["raw_material_qc"] = qc_payload
    order.metadata_ = meta
    saved_qc_status = str(meta["raw_material_qc"].get("qc_status") or "").upper()
    if ac_stock.qc_status_passed(saved_qc_status):
        order.status = "QC_PASSED"
    elif saved_qc_status in ("FAIL", "QC_FAILED", "REJECTED"):
        order.status = "QC_FAILED"
    _stage_inward_qc_triples(db, tenant, order, qc_payload)
    repo.db.commit()
    repo.db.refresh(order)
    row = _raw_material_qc_from_order(db, tenant, order)
    assert row is not None
    return row


def create_kiln_feed_lot(
    db: Session, tenant: TenantContext, payload: AcKilnFeedLotCreate
) -> ProductionLotOut:
    repo = _repo(db, tenant)

    lot = None
    if payload.production_lot_id is not None:
        lot = repo.get_by_pk(
            ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
        )
    elif payload.lot_code:
        lot = repo.get_by_code(
            ProductionLot, ProductionLot.lot_code, payload.lot_code.strip()
        )

    if lot is not None:
        lot_status = (lot.status or "").upper()
        if lot_status not in ("CREATED",):
            raise WorkflowError(
                f"Lot '{lot.lot_code}' is already charged or in progress (status: {lot.status})"
            )
        if not is_ready_for_scheduling(db, tenant, lot.lot_code):
            raise WorkflowError(
                "Feasibility Gate must pass before charging the kiln — "
                f"run feasibility for lot '{lot.lot_code}' first"
            )
        if payload.lot_quantity is not None:
            lot.lot_quantity = payload.lot_quantity
        lot.status = payload.status or "IN_PROGRESS"
        if payload.kiln_resource_code:
            _create_process_execution(
                db,
                tenant,
                lot.production_lot_id,
                "ACTIVATION",
                {"kiln_resource_code": payload.kiln_resource_code, "feed_recorded": True},
            )
        repo.db.commit()
        repo.db.refresh(lot)
        return mes_core_entities.get_production_lot(db, tenant, lot.production_lot_id)

    if payload.production_order_id is None or payload.lot_quantity is None:
        raise ValidationError(
            "production_order_id and lot_quantity are required when production_lot_id "
            "or lot_code is omitted"
        )

    lot_code = resolve_ac_business_code(
        db, provided=payload.lot_code, entity="ac_production_lot"
    )
    lot = mes_core_entities.create_production_lot(
        db,
        tenant,
        ProductionLotCreate(
            lot_code=lot_code,
            production_order_id=payload.production_order_id,
            lot_quantity=payload.lot_quantity,
            status=payload.status,
        ),
    )
    if payload.kiln_resource_code:
        if not is_ready_for_scheduling(db, tenant, lot.lot_code):
            raise WorkflowError(
                "Feasibility Gate must pass before charging the kiln — "
                f"run feasibility for lot '{lot.lot_code}' first"
            )
        _create_process_execution(
            db,
            tenant,
            lot.production_lot_id,
            "ACTIVATION",
            {"kiln_resource_code": payload.kiln_resource_code, "feed_recorded": True},
        )
    return lot


def create_kiln_parameters(
    db: Session, tenant: TenantContext, payload: AcKilnParametersCreate
) -> OperationExecutionOut:
    meta = {
        k: v
        for k, v in {
            "zone1_temp_c": payload.zone1_temp_c,
            "zone2_temp_c": payload.zone2_temp_c,
            "steam_flow_kg_h": payload.steam_flow_kg_h,
            "residence_time_min": payload.residence_time_min,
            "o2_pct": payload.o2_pct,
            "kiln_temp_c": payload.kiln_temp_c or payload.zone2_temp_c or payload.zone1_temp_c,
            "pressure_bar": payload.pressure_bar,
        }.items()
        if v is not None
    }
    return _create_process_execution(
        db, tenant, payload.production_lot_id, "ACTIVATION", meta
    )


def create_screening_record(
    db: Session, tenant: TenantContext, payload: AcScreeningCreate
) -> OperationExecutionOut:
    from app.services.industry.activated_carbon import stock as ac_stock

    meta = {
        k: v
        for k, v in {
            "mesh_size": payload.mesh_size,
            "overs_kg": payload.overs_kg,
            "fines_kg": payload.fines_kg,
            "good_kg": payload.good_kg,
        }.items()
        if v is not None
    }
    result = _create_process_execution(
        db, tenant, payload.production_lot_id, "SCREENING", meta
    )
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
    )
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    lot.metadata_ = {
        **lot_meta,
        "screening_recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    repo.db.flush()
    ac_stock.try_stock_lot_after_pipeline(db, tenant, payload.production_lot_id)
    return result


def create_quality_test(
    db: Session, tenant: TenantContext, payload: AcQualityTestCreate
) -> QualityCheckOut:
    from app.services.industry.activated_carbon import stock as ac_stock

    check_code = resolve_ac_business_code(db, provided=None, entity="ac_quality_check")
    qc_status = (payload.status or "OPEN").upper()
    check = mes_core_entities.create_quality_check(
        db,
        tenant,
        QualityCheckCreate(
            check_code=check_code,
            production_lot_id=payload.production_lot_id,
            check_type="FINAL",
            status=qc_status,
        ),
    )
    repo = _repo(db, tenant)
    check_row = repo.get_by_pk(
        QualityCheck, QualityCheck.quality_check_id, check.quality_check_id
    )
    check_row.metadata_ = {
        **(check_row.metadata_ if isinstance(check_row.metadata_, dict) else {}),
        "iodine_mg_g": payload.iodine_mg_g,
        "ash_pct": payload.ash_pct,
        "moisture_pct": payload.moisture_pct,
        "bulk_density": payload.bulk_density,
        "remarks": payload.remarks,
    }
    lot = repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
    )
    if payload.iodine_mg_g:
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:lot:{lot.lot_code}",
                predicate_uri="urn:nyra:hasIodineValue",
                object_literal=str(payload.iodine_mg_g),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="qms.quality_check",
            ),
        )
    repo.db.commit()
    repo.db.refresh(check_row)
    disposition = qc_status
    if disposition in ("FAIL", "FAILED", "REJECT", "REJECTED", "SCRAP", "SCRAPPED", "HOLD"):
        if disposition != "HOLD":
            ac_stock.scrap_lot_after_qc(
                db, tenant, payload.production_lot_id, reason=disposition
            )
    elif ac_stock.qc_status_passed(qc_status):
        ac_stock.try_stock_lot_after_pipeline(db, tenant, payload.production_lot_id)
    return QualityCheckOut.model_validate(check_row)
