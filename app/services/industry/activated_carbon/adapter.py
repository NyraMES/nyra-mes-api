"""Activated Carbon industry adapter — reuses common nyra_mes_core MES tables."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
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
    AcDeliveryCommitmentOut,
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
        return True
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
    metadata: dict = {"flow": "CUSTOMER_SALES"}
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


def create_make_to_stock_production_order(
    db: Session, tenant: TenantContext, payload: AcMakeToStockCreate
) -> AcMakeToStockCreateResponse:
    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)
    finished: Product
    source_inward_id: Optional[UUID] = payload.inward_order_id

    if source_inward_id is not None:
        inward = repo.get_by_pk(
            CustomerOrder, CustomerOrder.customer_order_id, source_inward_id
        )
        meta = inward.metadata_ if isinstance(inward.metadata_, dict) else {}
        if meta.get("flow") != "RAW_MATERIAL_INWARD":
            raise ValidationError("Order is not a raw material inward receipt")
        raw_product_id = meta.get("raw_product_id")
        if raw_product_id:
            finished = _resolve_finished_product_for_raw(
                db, tenant, UUID(str(raw_product_id))
            )
        else:
            finished = _resolve_finished_product(repo)
        release_qty = Decimal(str(payload.quantity))
        remaining = ac_stock.allocate_raw_from_inward(
            db, tenant, source_inward_id, release_qty
        )
        meta = {
            **meta,
            "last_release_kg": str(release_qty),
            "available_after_release_kg": str(remaining),
        }
        inward.metadata_ = meta
        repo.db.flush()
    elif payload.finished_product_id is not None:
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
        source_inward_order_id=source_inward_id,
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
    if source_inward_id is not None:
        po_row.metadata_["source_inward_order_id"] = str(source_inward_id)
    repo.db.commit()
    return AcMakeToStockCreateResponse(
        order=order_resp.order,
        line=order_resp.line,
        production_order=po_out,
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
    repo = _repo(db, tenant)
    orders = repo.query(ProductionOrder).all()
    lots = repo.query(ProductionLot).all()
    planned = sum(Decimal(str(o.planned_quantity or 0)) for o in orders)
    lot_qty = sum(Decimal(str(l.lot_quantity or 0)) for l in lots)
    accepted = Decimal("0")
    for row in repo.query(QualityCheck).filter(QualityCheck.check_type != "DISPATCH").all():
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        for key in ("accepted_quantity", "accepted_kg", "accepted_qty"):
            if meta.get(key) is not None:
                accepted += Decimal(str(meta[key]))
                break
    avg_yield: Optional[Decimal] = None
    if accepted > 0 and lot_qty > 0:
        avg_yield = (accepted / lot_qty * Decimal("100")).quantize(Decimal("0.01"))
    elif planned > 0:
        basis = min(lot_qty, planned)
        avg_yield = (basis / planned * Decimal("100")).quantize(Decimal("0.01"))
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
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    raw_inward_order_ids: set = set()
    ordered = Decimal("0")
    for line in repo.query(CustomerOrderLine).all():
        product = products.get(line.product_id)
        if product and _is_raw_product(product):
            ordered += Decimal(str(line.quantity or 0))
            raw_inward_order_ids.add(line.order_id)
    for order in repo.query(CustomerOrder).all():
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        if meta.get("flow") == "RAW_MATERIAL_INWARD":
            raw_inward_order_ids.add(order.customer_order_id)
    inward_line_ids = {
        line.order_line_id
        for line in repo.query(CustomerOrderLine).all()
        if line.order_id in raw_inward_order_ids
    }
    raw_po_ids = {
        po.production_order_id
        for po in repo.query(ProductionOrder).all()
        if po.order_line_id in inward_line_ids
    }
    charged = sum(
        Decimal(str(l.lot_quantity or 0))
        for l in repo.query(ProductionLot).all()
        if l.production_order_id in raw_po_ids
    )
    pending = max(Decimal("0"), ordered - charged)
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
        status = "IDLE"
        if lot:
            lot_status = (lot.status or "").upper()
            if lot_status in {"IN_PROGRESS", "ACTIVE", "RUNNING"}:
                status = "RUNNING"
            elif lot_status in {"COMPLETED", "CLOSED"}:
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
    order_count = repo.query(CustomerOrder).count()
    lot_count = repo.query(ProductionLot).count()
    feasibility_count = repo.query(FeasibilityCheck).count()
    execution_count = repo.query(OperationExecution).count()
    routing_count = lot_count
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
        "AC_RAW_MATERIAL_INWARD": order_count,
        "AC_RAW_MATERIAL_QC": sum(
            1
            for order in repo.query(CustomerOrder).all()
            if isinstance(order.metadata_, dict)
            and isinstance(order.metadata_.get("raw_material_qc"), dict)
            and order.metadata_["raw_material_qc"].get("qc_status") not in (None, "", "PENDING")
        ),
        "AC_KILN_FEED": lot_count,
        "FEASIBILITY": feasibility_count,
        "EXECUTION": execution_count,
        "ROUTING": routing_count,
        "AC_HOURLY_KILN_PARAMETERS": activation_count,
        "AC_SCREENING": screening_count,
        "AC_QUALITY_TESTING": qc_count,
        "AC_YIELD_ANALYSIS": lot_count,
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
    dispatch_count = len(mes_core_dispatch.list_dispatches(db, tenant))
    return AcDashboardOut(
        yield_summary=yield_summary,
        raw_material=raw_material,
        kilns=kilns,
        process_steps=process_steps,
        lot_lines=lot_lines,
        active_orders=active_orders,
        quality_check_count=qc_count,
        dispatch_count=dispatch_count,
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
                quantity=line_qty,
                uom=line_uom,
                status="OPEN",
            ),
        )
        finished_line_id = finished_line_out.order_line_id
    else:
        finished_line_id = finished_line.order_line_id

    existing_po = (
        repo.query(ProductionOrder)
        .filter(ProductionOrder.order_line_id == finished_line_id)
        .first()
    )
    if existing_po:
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
            planned_quantity=line_qty,
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
    repo.db.flush()
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
        operator_remarks=qc.get("operator_remarks"),
        qc_status=qc.get("qc_status") or "PENDING",
        qc_at=qc.get("qc_at"),
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
    if prior_status in ("PASS", "FAIL", "QC_PASSED", "QC_FAILED"):
        raise ValidationError(
            f"Order '{order.order_code}' already has QC status {prior_status} — "
            "select a pending inward order instead."
        )

    meta = dict(order.metadata_ if isinstance(order.metadata_, dict) else {})

    def _json_val(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    meta["raw_material_qc"] = {
        k: _json_val(v)
        for k, v in {
            "moisture_pct": payload.moisture_pct,
            "ash_pct": payload.ash_pct,
            "foreign_matter_pct": payload.foreign_matter_pct,
            "operator_remarks": payload.operator_remarks,
            "qc_status": (payload.qc_status or "PASS").upper(),
            "qc_at": datetime.now(timezone.utc).isoformat(),
        }.items()
        if v is not None
    }
    order.metadata_ = meta
    if meta["raw_material_qc"].get("qc_status") == "PASS":
        order.status = "QC_PASSED"
    elif meta["raw_material_qc"].get("qc_status") == "FAIL":
        order.status = "QC_FAILED"
    repo.db.commit()
    repo.db.refresh(order)
    row = _raw_material_qc_from_order(db, tenant, order)
    assert row is not None
    return row


def create_kiln_feed_lot(
    db: Session, tenant: TenantContext, payload: AcKilnFeedLotCreate
) -> ProductionLotOut:
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
    return _create_process_execution(
        db, tenant, payload.production_lot_id, "SCREENING", meta
    )


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
    if ac_stock.qc_status_passed(qc_status):
        ac_stock.stock_lot_after_final_qc(db, tenant, payload.production_lot_id)
    return QualityCheckOut.model_validate(check_row)
