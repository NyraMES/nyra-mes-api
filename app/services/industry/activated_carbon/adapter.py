"""Activated Carbon industry adapter — reuses common nyra_mes_core MES tables."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4
from typing import Any, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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
    Supplier,
    TripleStoreStaging,
)
from app.schemas.mes_core.schemas import (
    AcActiveOrderOut,
    AcDashboardOut,
    AcLotLineOut,
    AcOpenLotOut,
    AcKilnFeedLotCreate,
    AcKilnOutputBagCreate,
    AcKilnOutputBagOut,
    AcKilnOutputBagQcCreate,
    AcKilnOutputBagQcOut,
    AcDestoningBagOut,
    AcDestoningLoadEventOut,
    AcDestoningKilnGroupOut,
    AcDestonerCreate,
    AcDestonerDailyCtcOut,
    AcDestonerDailyCtcRow,
    AcDestonerDailyCtcSave,
    AcKilnSetpointChange,
    AcKilnSetpointRow,
    AcKilnSetpointsOut,
    AcKilnSetpointsSave,
    AcWorkOrderCreate,
    AcWorkOrderListOut,
    AcWorkOrderOut,
    AcDestonerMachineOut,
    AcDestoningStateOut,
    AcDestoningLoadCreate,
    AcDestoningOutputCreate,
    AcDestoningBagQcCreate,
    AcDestoningBagQcOut,
    AcKilnFeedChipOut,
    AcKilnOutputListOut,
    AcKilnCreate,
    AcKilnOut,
    AcPlantResourceOut,
    AcKilnParametersCreate,
    AcKilnParameterReadingOut,
    AcKilnStatusOut,
    AcMastersOut,
    AcProcessStepOut,
    AcQualityTestCreate,
    AcCustomerSalesOrderCreate,
    AcCustomerSalesOrderCreateResponse,
    AcDeliveryCommitmentOut,
    AcDispatchFromOrderCreate,
    AcDispatchFromOrderResponse,
    AcGradeStockOut,
    AcInStockBagOut,
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
    AcRawMaterialCrushCreate,
    AcRawMaterialCrushOut,
    AcInboundStepCompleteCreate,
    AcInboundExecutionOut,
    AcInboundStepStatusOut,
    AcRawMaterialStatusOut,
    AcRoutingMasterOut,
    AcRoutingOperationSummary,
    AcScreeningCreate,
    AcGradeSeparationCreate,
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
    ResourceUpdate,
    SupplierCreate,
    SupplierOut,
    TripleCreate,
    TripleOut,
)
from app.services.industry.activated_carbon.codes import (
    AC_ID_PAD_WIDTH,
    kiln_output_id_prefix,
    next_destoning_bag_code,
    next_kiln_output_bag_code,
    plant_today,
    resolve_ac_business_code,
    sync_ac_sequences,
)
from app.services.industry.activated_carbon import post_activation as ac_post_activation
from app.services.industry.activated_carbon import station_machines as ac_station_machines
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
from app.services.industry.activated_carbon import inbound_admin as ac_inbound_admin
from app.services.industry.activated_carbon import inbound_execution as ac_inbound_execution
from app.services.industry.activated_carbon import inbound_workflow as ac_inbound_workflow
from app.services.industry.activated_carbon import isa95_rag as ac_isa95_rag
from app.services.industry.activated_carbon import lot_routing as ac_lot_routing
from app.services.industry.activated_carbon import stock as ac_stock
from app.services.industry.activated_carbon.resource_pool import (
    claim_kiln_for_lot,
    kiln_release_step,
    release_lot_kiln_if_claimed,
)
from app.schemas.traceability import TraceabilityResponse
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core import dispatch_workflow as mes_core_dispatch
from app.services.mes_core import traceability_workflow as mes_core_traceability
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _uuid_or_none(value) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


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
    from app.services.industry.activated_carbon.station_machines import (
        monthly_capacity_kg_of,
        station_of,
    )

    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    unit_count = None
    if meta.get("unit_count") not in (None, ""):
        try:
            unit_count = int(meta.get("unit_count"))
        except (TypeError, ValueError):
            unit_count = None
    rtype = (row.resource_type or "").upper()
    monthly = None
    if rtype == "MACHINE" or (row.resource_code or "").upper().startswith("RES-KILN"):
        monthly = monthly_capacity_kg_of(row)
    return ResourceOut(
        resource_id=row.resource_id,
        tenant_id=row.tenant_id,
        resource_code=row.resource_code,
        resource_name=row.resource_name,
        resource_type=row.resource_type,
        status=row.status,
        station=station_of(row),
        unit_count=unit_count,
        monthly_capacity_kg=monthly,
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
        db,
        provided=payload.supplier_code,
        entity="ac_supplier",
        tenant_id=tenant.tenant_id,
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
        return sorted(
            kiln_rows,
            key=lambda row: (
                kiln_output_id_prefix(row.resource_name or "", row.resource_code or ""),
                row.resource_code or "",
            ),
        )
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

    from app.services.industry.activated_carbon import process_rules as ac_process_rules

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
            if not ac_process_rules.is_kiln_feed_bag_qc_step(
                {
                    "operation_code": op.operation_code,
                    "operation_name": op.operation_name,
                }
            )
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
    released_at_by_inward: dict[str, datetime] = {}
    for po in repo.query(ProductionOrder).all():
        po_meta = po.metadata_ if isinstance(po.metadata_, dict) else {}
        inward_id = po_meta.get("source_inward_order_id")
        if not inward_id or not po.created_at:
            continue
        key = str(inward_id)
        prev = released_at_by_inward.get(key)
        if prev is None or po.created_at < prev:
            released_at_by_inward[key] = po.created_at

    out: List[CustomerOrderOut] = []
    for row in rows:
        order_out = mes_core_entities._customer_order_out(db, tenant, row)
        if _order_is_raw_material_inward(row, order_out, products):
            out.append(
                ac_stock.enrich_inward_order_stock(
                    order_out,
                    row,
                    products,
                    released_at_fallback=released_at_by_inward.get(str(row.customer_order_id)),
                )
            )
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


def _lot_finished_product_map(db: Session, tenant: TenantContext) -> dict[str, UUID]:
    repo = _repo(db, tenant)
    mapping: dict[str, UUID] = {}
    for lot in repo.query(ProductionLot).all():
        if not lot.lot_code:
            continue
        try:
            product_id = ac_stock._lot_finished_product_id(db, tenant, lot)
        except Exception:
            product_id = None
        if product_id:
            mapping[str(lot.lot_code)] = product_id
    return mapping


def _in_stock_bags_for_product(
    db: Session, tenant: TenantContext, product_id: Optional[UUID]
) -> list[dict]:
    bags = ac_post_activation.list_available_in_stock_bags(db, tenant)
    if product_id is None:
        return bags
    mapping = _lot_finished_product_map(db, tenant)
    matched: list[dict] = []
    unmatched: list[dict] = []
    for bag in bags:
        lot_code = str(bag.get("lot_code") or "")
        mapped = mapping.get(lot_code) if lot_code else None
        if mapped == product_id:
            matched.append(bag)
        elif mapped is None:
            unmatched.append(bag)
    return matched + unmatched


def _in_stock_kg_for_product(
    db: Session, tenant: TenantContext, product_id: Optional[UUID]
) -> Decimal:
    return sum(
        (
            Decimal(str(bag.get("remaining_kg") or 0))
            for bag in _in_stock_bags_for_product(db, tenant, product_id)
        ),
        Decimal("0"),
    )


def _available_stock_kg(
    db: Session, tenant: TenantContext, product_id: UUID
) -> Decimal:
    return _in_stock_kg_for_product(db, tenant, product_id) + ac_stock.get_fg_stock_kg(
        db, tenant, product_id
    )


def list_finished_goods_stock(
    db: Session, tenant: TenantContext
) -> List[AcFinishedGoodsStockOut]:
    repo = _repo(db, tenant)
    routable = _routable_product_ids(repo)
    rows = repo.query(Product).order_by(Product.product_code).all()
    mapping = _lot_finished_product_map(db, tenant)
    bags = ac_post_activation.list_available_in_stock_bags(db, tenant)
    in_stock_by_product: dict[UUID, Decimal] = {}
    unmatched = Decimal("0")
    for bag in bags:
        qty = Decimal(str(bag.get("remaining_kg") or 0))
        lot_code = str(bag.get("lot_code") or "")
        mapped = mapping.get(lot_code) if lot_code else None
        if mapped:
            in_stock_by_product[mapped] = in_stock_by_product.get(mapped, Decimal("0")) + qty
        else:
            unmatched += qty
    out: list[AcFinishedGoodsStockOut] = []
    unmatched_added = False
    for row in rows:
        if row.product_id not in routable:
            code = (row.product_code or "").upper()
            if code != FINISHED_PRODUCT_CODE and row.product_id not in in_stock_by_product:
                continue
        qty = in_stock_by_product.get(row.product_id, Decimal("0")) + ac_stock.get_fg_stock_kg(
            db, tenant, row.product_id
        )
        if not unmatched_added and unmatched > 0:
            qty += unmatched
            unmatched_added = True
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
    if unmatched > 0 and not unmatched_added:
        fallback = next((row for row in rows if row.product_id in routable), None)
        if fallback is None and rows:
            fallback = rows[0]
        if fallback is not None:
            out.append(
                AcFinishedGoodsStockOut(
                    product_id=fallback.product_id,
                    product_code=fallback.product_code,
                    product_name=fallback.product_name,
                    quantity_kg=unmatched,
                    uom=fallback.uom or "KG",
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
    stock = _available_stock_kg(db, tenant, finished_product_id)
    qty = Decimal(str(quantity))
    shortfall = max(qty - stock, Decimal("0"))
    raw_avail = ac_stock.available_raw_material_kg(db, tenant)
    today = plant_today(tenant.timezone)

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
                f"{stock} KG available in stock — quantity can be dispatched without "
                "new production."
            ),
        )

    lead_days = ac_stock.estimate_manufacturing_days(
        db, tenant, finished_product_id, shortfall
    )
    tentative = today + timedelta(days=lead_days)
    if raw_avail < shortfall:
        message = (
            f"In stock covers {stock} KG; need {shortfall} KG more. Raw material on hand "
            f"({raw_avail} KG) is insufficient — procure feedstock before promising "
            f"{tentative.isoformat()}."
        )
    else:
        message = (
            f"In stock covers {stock} KG; manufacturing ~{lead_days} shop days for "
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
        db,
        provided=payload.order_code,
        entity="ac_customer_po",
        tenant_id=tenant.tenant_id,
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
    mapping = _lot_finished_product_map(db, tenant)

    for bag in ac_post_activation.list_available_in_stock_bags(db, tenant):
        qty = Decimal(str(bag.get("remaining_kg") or 0))
        if qty <= 0:
            continue
        grade_label = str(bag.get("grade") or "In Stock").strip() or "In Stock"
        grade_code = re.sub(r"[^a-z0-9]+", "-", grade_label.lower()).strip("-") or "in-stock"
        key = grade_code.upper()
        lot_code = str(bag.get("lot_code") or "")
        product_id = mapping.get(lot_code) if lot_code else None
        product = products.get(product_id) if product_id else None
        lot_counts[key] = lot_counts.get(key, 0) + 1
        existing = buckets.get(key)
        if existing:
            buckets[key] = existing.model_copy(
                update={
                    "quantity_kg": existing.quantity_kg + qty,
                    "stocked_lot_count": lot_counts[key],
                    "product_id": existing.product_id or product_id,
                    "product_code": existing.product_code or (product.product_code if product else None),
                }
            )
        else:
            buckets[key] = AcGradeStockOut(
                grade_code=grade_code,
                grade_label=grade_label,
                product_id=product_id,
                product_code=product.product_code if product else None,
                quantity_kg=qty,
                uom="KG",
                source="in_stock",
                stocked_lot_count=1,
            )

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


def _ensure_customer_sales_po_codes(db: Session, tenant: TenantContext) -> None:
    """Rewrite leftover CUSTOMER_SALES ORD-AC-* codes to CUST_PO_."""
    repo = _repo(db, tenant)
    changed = False
    for order in repo.query(CustomerOrder).all():
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        if meta.get("flow") != "CUSTOMER_SALES":
            continue
        code = str(order.order_code or "")
        if not code.upper().startswith("ORD-AC-"):
            continue
        order.order_code = resolve_ac_business_code(
            db, provided=None, entity="ac_customer_po", tenant_id=tenant.tenant_id
        )
        changed = True
    if changed:
        repo.db.commit()


def list_in_stock_bags_for_dispatch(
    db: Session, tenant: TenantContext
) -> list[AcInStockBagOut]:
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    mapping = _lot_finished_product_map(db, tenant)
    rows: list[AcInStockBagOut] = []
    for bag in ac_post_activation.list_available_in_stock_bags(db, tenant):
        lot_code = str(bag.get("lot_code") or "")
        product_id = mapping.get(lot_code) if lot_code else None
        product = products.get(product_id) if product_id else None
        wo_code = str(bag.get("work_order_code") or "").strip() or None
        rows.append(
            AcInStockBagOut(
                bag_code=str(bag.get("bag_code") or ""),
                remaining_kg=Decimal(str(bag.get("remaining_kg") or 0)),
                quantity_kg=Decimal(str(bag.get("quantity_kg") or 0)),
                grade=bag.get("grade"),
                lot_code=bag.get("lot_code"),
                work_order_code=wo_code,
                work_order_ctc=ac_work_orders.lookup_work_order_ctc(db, tenant, wo_code),
                product_id=product_id,
                product_code=product.product_code if product else None,
                source=bag.get("source"),
                created_at=bag.get("created_at"),
            )
        )
    return rows


def list_open_customer_sales_orders(
    db: Session, tenant: TenantContext
) -> list[AcOpenCustomerOrderOut]:
    _ensure_customer_sales_po_codes(db, tenant)
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
        stock = _available_stock_kg(db, tenant, line.product_id)
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


def _in_stock_bags_for_work_order(
    db: Session, tenant: TenantContext, work_order_code: str
) -> list[dict]:
    wanted = (work_order_code or "").strip()
    return [
        bag
        for bag in ac_post_activation.list_available_in_stock_bags(db, tenant)
        if ac_post_activation.bag_matches_work_order(bag, wanted)
    ]


def assert_dispatch_within_selected(
    quantity_kg: Decimal,
    selected_kg: Decimal,
    *,
    bag_code: str | None = None,
) -> None:
    """A shipment cannot take kilograms from a bag that was not selected."""
    if quantity_kg <= selected_kg:
        return
    if bag_code:
        raise ValidationError(
            f"Bag {bag_code} has {selected_kg} KG remaining. Requested {quantity_kg} KG."
        )
    raise ValidationError(
        f"Selected bags have {selected_kg} KG. Requested {quantity_kg} KG."
    )


def assert_rms_outward_before_release(meta: dict, order_code: str) -> None:
    separation = meta.get("grade_separation") if isinstance(meta.get("grade_separation"), dict) else {}
    if str(separation.get("status") or "").upper() != "COMPLETED":
        raise ValidationError(
            f"Complete RMS outward on {order_code} before release to production."
        )


def assert_destoner_output_within_load(loaded_kg: Decimal, already: Decimal, out_kg: Decimal) -> None:
    remaining = loaded_kg - already
    if loaded_kg <= 0 or remaining <= Decimal("0.001"):
        raise ValidationError("Load bags onto the destoner first.")
    if out_kg > remaining + Decimal("0.001"):
        raise ValidationError(
            f"Destoner output cannot exceed loaded ({loaded_kg} KG). Remaining: {remaining} KG."
        )


def _consume_work_order_stock(
    db: Session,
    tenant: TenantContext,
    *,
    work_order_code: str,
    quantity_kg: Decimal,
    bag_code: str | None,
    bag_codes: list[str] | None = None,
) -> list[dict]:
    bags = _in_stock_bags_for_work_order(db, tenant, work_order_code)
    wanted: list[str] = []
    for raw in bag_codes or []:
        code = str(raw or "").strip()
        if code and code not in wanted:
            wanted.append(code)
    single = (bag_code or "").strip()
    if single and single not in wanted:
        wanted.insert(0, single)
    by_code = {str(bag.get("bag_code") or ""): bag for bag in bags}
    if wanted:
        chosen = []
        for code in wanted:
            bag = by_code.get(code)
            if bag is None:
                raise ValidationError(
                    f"Bag '{code}' is not in stock for work order {work_order_code}."
                )
            chosen.append(bag)
        order = {str(bag.get("bag_code") or ""): index for index, bag in enumerate(bags)}
        chosen.sort(key=lambda bag: order.get(str(bag.get("bag_code") or ""), 0))
    elif bags:
        chosen = [bags[0]]
    else:
        chosen = []
    if not chosen:
        raise ValidationError(f"Work order {work_order_code} has no bags in stock.")
    selected_kg = sum(
        (Decimal(str(bag.get("remaining_kg") or 0)) for bag in chosen),
        Decimal("0"),
    )
    assert_dispatch_within_selected(
        quantity_kg,
        selected_kg,
        bag_code=str(chosen[0].get("bag_code") or "") if len(chosen) == 1 else None,
    )
    consumed = ac_post_activation.consume_in_stock_bags(
        db,
        tenant,
        quantity_kg,
        bag_codes={str(bag.get("bag_code") or "") for bag in chosen},
        work_order_code=work_order_code,
    )
    taken = sum(
        (Decimal(str(row.get("consumed_kg") or 0)) for row in consumed),
        Decimal("0"),
    )
    if taken + Decimal("0.001") < quantity_kg:
        raise ValidationError(
            f"Selected bags can supply {taken} KG. Requested {quantity_kg} KG."
        )
    return consumed


def _lot_from_consumed_bags(
    db: Session, tenant: TenantContext, consumed: list[dict], lot_code: str | None = None
) -> ProductionLot | None:
    repo = _repo(db, tenant)
    wanted = (lot_code or "").strip()
    codes: list[str] = []
    if wanted:
        codes.append(wanted)
    for bag in consumed:
        code = str(bag.get("lot_code") or "").strip()
        if code and code not in codes:
            codes.append(code)
    for code in codes:
        lot = repo.query(ProductionLot).filter(ProductionLot.lot_code == code).first()
        if lot is not None:
            return lot
    return None


def _create_ac_dispatch_from_work_order(
    db: Session, tenant: TenantContext, payload: AcDispatchFromOrderCreate
) -> AcDispatchFromOrderResponse:
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)
    wo_code = (payload.work_order_code or "").strip()
    work_order = ac_work_orders.get_work_order(db, tenant, wo_code)
    qty = Decimal(str(payload.quantity_kg))
    ordered = Decimal(str(work_order.get("quantity_kg") or 0))
    already = _dispatch_kg_by_work_order(db, tenant).get(wo_code, Decimal("0"))
    pending = ac_work_orders.pending_dispatch_kg(ordered, already)
    if qty > pending:
        raise ValidationError(
            f"Work order {wo_code} has {pending} KG pending. "
            f"Already dispatched {already} KG. Requested {qty} KG."
        )
    consumed = _consume_work_order_stock(
        db,
        tenant,
        work_order_code=wo_code,
        quantity_kg=qty,
        bag_code=payload.bag_code,
        bag_codes=list(payload.bag_codes or []),
    )
    lot = _lot_from_consumed_bags(db, tenant, consumed, payload.lot_code)
    if lot is None:
        raise ValidationError(
            f"No production lot on in-stock bags for {wo_code}. Complete activation first."
        )
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    now_iso = datetime.now(timezone.utc).isoformat()
    lot.metadata_ = {**lot_meta, "last_dispatch_kg": str(qty), "last_dispatch_at": now_iso}

    order = None
    order_meta: dict = {}
    order_status = "SHIPPED"
    order_code = wo_code
    remaining_after = max(pending - qty, Decimal("0"))
    dispatch_code = resolve_ac_business_code(db, provided=None, entity="ac_dispatch")
    if payload.customer_order_id:
        order = repo.get_by_pk(
            CustomerOrder, CustomerOrder.customer_order_id, payload.customer_order_id
        )
        order_meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        if order_meta.get("flow") == "CUSTOMER_SALES":
            lines = (
                repo.query(CustomerOrderLine)
                .filter(CustomerOrderLine.order_id == order.customer_order_id)
                .all()
            )
            line = lines[0] if lines else None
            ordered = Decimal(str(order_meta.get("ordered_kg") or (line.quantity if line else 0) or 0))
            dispatched = Decimal(str(order_meta.get("dispatched_kg") or 0))
            remaining = max(ordered - dispatched, Decimal("0"))
            if qty > remaining:
                raise ValidationError(
                    f"Dispatch quantity {qty} KG exceeds remaining PO quantity {remaining} KG"
                )
            dispatched += qty
            remaining_po = max(ordered - dispatched, Decimal("0"))
            order.status = "CLOSED" if remaining_po <= 0 else "PARTIAL"
            order.metadata_ = {
                **order_meta,
                "dispatched_kg": str(dispatched),
                "last_dispatch_id": dispatch_code,
                "last_dispatch_lot": lot.lot_code,
                "last_dispatch_kg": str(qty),
            }
            remaining_after = remaining_po
            order_status = order.status or "OPEN"
            order_code = order.order_code

    customer = None
    if order is not None and order.customer_id:
        customer = repo.get_by_pk(Customer, Customer.customer_id, order.customer_id)
    grade_code = payload.grade_code or work_order.get("grade") or (consumed[0].get("grade") if consumed else None)
    dispatch_meta = {
        "customer_id": customer.customer_code if customer else None,
        "order_id": order_code,
        "customer_order_id": str(order.customer_order_id) if order is not None else None,
        "work_order_code": wo_code,
        "grade_code": grade_code,
        "vehicle_number": payload.vehicle_number,
        "transporter_name": payload.transporter_name,
        "dispatch_status": "Shipped",
        "dispatch_date": datetime.now(timezone.utc).isoformat(),
        "remarks": payload.remarks,
        "lines": [
            {
                "lot_id": lot.lot_code,
                "part_id": grade_code,
                "dispatch_quantity": str(qty),
                "accepted_quantity": str(qty),
                "rejected_quantity": "0",
                "bag_codes": [str(row.get("bag_code") or "") for row in consumed if row.get("bag_code")],
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
    repo.db.commit()
    stock_after = sum(
        (
            Decimal(str(bag.get("remaining_kg") or 0))
            for bag in _in_stock_bags_for_work_order(db, tenant, wo_code)
        ),
        Decimal("0"),
    )
    return AcDispatchFromOrderResponse(
        dispatch_id=dispatch_code,
        order_code=order_code,
        work_order_code=wo_code,
        lot_code=lot.lot_code,
        grade_code=grade_code,
        quantity_kg=qty,
        remaining_on_order_kg=remaining_after,
        order_status=order_status,
        stock_on_hand_after_kg=stock_after,
    )


def create_ac_dispatch_from_order(
    db: Session, tenant: TenantContext, payload: AcDispatchFromOrderCreate
) -> AcDispatchFromOrderResponse:
    if (payload.work_order_code or "").strip():
        return _create_ac_dispatch_from_work_order(db, tenant, payload)
    if payload.customer_order_id is None:
        raise ValidationError("Choose a work order number.")
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

    stock = _available_stock_kg(db, tenant, line.product_id)
    if qty > stock:
        commitment = evaluate_delivery_commitment(
            db, tenant, finished_product_id=line.product_id, quantity=qty
        )
        raise ValidationError(
            f"Insufficient stock for {product.product_code}: "
            f"on hand {stock} KG, requested {qty} KG. {commitment.message}"
        )

    in_stock_bags = _in_stock_bags_for_product(db, tenant, line.product_id)
    in_stock_kg = sum(
        (Decimal(str(bag.get("remaining_kg") or 0)) for bag in in_stock_bags),
        Decimal("0"),
    )
    from_bags = min(qty, in_stock_kg)
    from_meta = qty - from_bags
    eligible_codes = {
        str(bag.get("bag_code") or "") for bag in in_stock_bags if bag.get("bag_code")
    }
    preferred = (payload.bag_code or "").strip()
    consumed = []
    if from_bags > 0:
        remaining_bags = from_bags
        if preferred and preferred in eligible_codes:
            first = ac_post_activation.consume_in_stock_bags(
                db, tenant, remaining_bags, bag_codes={preferred}
            )
            consumed.extend(first)
            remaining_bags -= sum(
                (Decimal(str(row.get("consumed_kg") or 0)) for row in first),
                Decimal("0"),
            )
        if remaining_bags > 0:
            rest_codes = eligible_codes - ({preferred} if preferred else set())
            consumed.extend(
                ac_post_activation.consume_in_stock_bags(
                    db, tenant, remaining_bags, bag_codes=rest_codes or None
                )
            )
    dispatch_lot_code = payload.lot_code
    if preferred and not dispatch_lot_code:
        preferred_bag = next(
            (bag for bag in (consumed or in_stock_bags) if str(bag.get("bag_code") or "") == preferred),
            None,
        )
        if preferred_bag and preferred_bag.get("lot_code"):
            dispatch_lot_code = preferred_bag.get("lot_code")

    lot = None
    if dispatch_lot_code:
        try:
            lot = _stocked_lot_for_product(
                db, tenant, line.product_id, lot_code=dispatch_lot_code
            )
        except ValidationError:
            lot = repo.query(ProductionLot).filter(ProductionLot.lot_code == dispatch_lot_code).first()
    if lot is None:
        for bag in consumed or in_stock_bags:
            lot_code = str(bag.get("lot_code") or "")
            if not lot_code:
                continue
            lot = repo.query(ProductionLot).filter(ProductionLot.lot_code == lot_code).first()
            if lot is not None:
                break
    if lot is None and from_meta > 0:
        lot = _stocked_lot_for_product(db, tenant, line.product_id)
    if lot is None:
        for lot_row in repo.query(ProductionLot).order_by(ProductionLot.created_at.desc()).all():
            try:
                if ac_stock._lot_finished_product_id(db, tenant, lot_row) == line.product_id:
                    lot = lot_row
                    break
            except Exception:
                continue
    if lot is None:
        raise ValidationError(
            "No in-stock bag or stocked lot available for this product — "
            "set destoning or post-activation destination to In Stock first."
        )

    ac_stock.release_lot_schedule_resources(db, tenant, lot.production_lot_id)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    now_iso = datetime.now(timezone.utc).isoformat()
    if from_meta > 0:
        ac_stock.deduct_fg_stock_kg(db, tenant, line.product_id, from_meta)
        lot_qty = Decimal(str(lot.lot_quantity or 0))
        if from_meta >= lot_qty and lot_meta.get("fg_stocked"):
            lot.status = "DISPATCHED"
            lot.metadata_ = {
                **lot_meta,
                "dispatched_at": now_iso,
                "fg_stocked": False,
                "fg_stock_kg_added": "0",
                "last_dispatch_kg": str(qty),
            }
        elif lot_meta.get("fg_stocked"):
            remaining_lot = max(lot_qty - from_meta, Decimal("0"))
            lot.lot_quantity = remaining_lot
            lot.metadata_ = {
                **lot_meta,
                "fg_stock_kg_added": str(remaining_lot),
                "last_dispatch_kg": str(qty),
            }
    else:
        lot.metadata_ = {
            **lot_meta,
            "last_dispatch_kg": str(qty),
            "last_dispatch_at": now_iso,
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

    stock_after = _available_stock_kg(db, tenant, line.product_id)
    return AcDispatchFromOrderResponse(
        dispatch_id=dispatch_code,
        order_code=order.order_code,
        work_order_code=(payload.work_order_code or "").strip() or None,
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
        already_allocated = Decimal(str(meta.get("allocated_to_production_kg") or 0))
        already_lots = meta.get("released_lots") if isinstance(meta.get("released_lots"), list) else []
        if already_allocated > 0 or already_lots or meta.get("released_to_production_at"):
            raise ValidationError(
                f"Inward {inward.order_code} is already released to production."
            )
        separation = (
            meta.get("grade_separation")
            if isinstance(meta.get("grade_separation"), dict)
            else {}
        )
        assert_rms_outward_before_release(meta, inward.order_code)

        release_qty = Decimal(str(payload.quantity))
        remaining = ac_stock.allocate_raw_from_inward(
            db, tenant, source_inward_id, release_qty
        )
        repo.db.refresh(inward)
        meta = dict(inward.metadata_ if isinstance(inward.metadata_, dict) else {})
        meta.update(
            {
                "last_release_kg": str(release_qty),
                "available_after_release_kg": str(remaining),
            }
        )

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
        raw_product_id = _uuid_or_none(meta.get("raw_product_id"))
        po_row.metadata_ = {
            **(po_row.metadata_ if isinstance(po_row.metadata_, dict) else {}),
            "flow": "RELEASED_TO_PRODUCTION",
            "source_inward_order_id": str(source_inward_id),
            "last_release_kg": str(release_qty),
            **(
                ac_lot_routing.production_order_meta_for_raw(
                    db, tenant, raw_product_id
                )
                if raw_product_id
                else {}
            ),
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

        split_entries: list[tuple[Decimal, Optional[str], Optional[str]]]
        if payload.lot_splits:
            split_entries = [
                (
                    Decimal(str(item.quantity_kg)),
                    item.grade_label,
                    None,
                )
                for item in payload.lot_splits
                if ac_inbound_workflow._is_kiln_feed_grade(item.grade_label or "")
            ]
            if any(q <= 0 for q, _, _ in split_entries):
                raise ValidationError("Each grade lot quantity must be greater than zero.")
            split_total = sum(q for q, _, _ in split_entries)
            if split_total != release_qty:
                raise ValidationError(
                    "Grade lot quantities must sum to the release quantity.",
                    details={
                        "release_quantity": str(release_qty),
                        "split_total": str(split_total),
                    },
                )
        elif payload.lot_quantities:
            split_entries = [(Decimal(str(q)), None, None) for q in payload.lot_quantities]
            if any(q <= 0 for q, _, _ in split_entries):
                raise ValidationError("Each lot quantity must be greater than zero.")
            split_total = sum(q for q, _, _ in split_entries)
            if split_total != release_qty:
                raise ValidationError(
                    "Lot split quantities must sum to the release quantity.",
                    details={
                        "release_quantity": str(release_qty),
                        "split_total": str(split_total),
                    },
                )
        else:
            separation = (
                meta.get("grade_separation")
                if isinstance(meta.get("grade_separation"), dict)
                else {}
            )
            auto_splits: list[tuple[Decimal, Optional[str], Optional[str]]] = []
            if separation.get("status") == "COMPLETED":
                for entry in separation.get("grade_splits") or []:
                    if not isinstance(entry, dict):
                        continue
                    grade = (entry.get("grade_label") or "").strip()
                    qty_raw = entry.get("quantity_kg")
                    if not grade or qty_raw is None:
                        continue
                    qty = Decimal(str(qty_raw))
                    if qty <= 0:
                        continue
                    if not ac_inbound_workflow._is_kiln_feed_grade(grade):
                        continue
                    auto_splits.append((qty, grade, None))
            auto_total = sum(q for q, _, _ in auto_splits)
            if auto_splits and auto_total == release_qty:
                split_entries = auto_splits
            else:
                split_entries = [(release_qty, None, None)]

        created_lots: list = []
        released_lot_rows: list[dict] = list(meta.get("released_lots") or [])
        for lot_qty, grade_label, _param_key in split_entries:
            lot_code = resolve_ac_business_code(
                db, provided=None, entity="ac_production_lot"
            )
            lot_out = mes_core_entities.create_production_lot(
                db,
                tenant,
                ProductionLotCreate(
                    lot_code=lot_code,
                    production_order_id=po_out.production_order_id,
                    lot_quantity=lot_qty,
                    status="CREATED",
                ),
            )
            lot_row = repo.get_by_pk(
                ProductionLot,
                ProductionLot.production_lot_id,
                lot_out.production_lot_id,
            )
            outward_src = ac_inbound_workflow._kiln_feed_outward_bags(meta)
            if grade_label:
                wanted = ac_inbound_admin._canonical_outward_grade(grade_label)
                matched = [
                    bag
                    for bag in outward_src
                    if ac_inbound_admin._canonical_outward_grade(
                        bag.get("grade") or bag.get("grade_label") or ""
                    )
                    == wanted
                ]
                if not matched:
                    matched = list(outward_src)
            else:
                matched = list(outward_src)
            outward_bags = [
                {
                    "bag_code": bag.get("bag_code"),
                    "grade": grade_label or bag.get("grade"),
                    "grade_label": grade_label or bag.get("grade") or bag.get("grade_label"),
                    "rotary": bag.get("rotary"),
                    "quantity_kg": bag.get("weight_kg") or bag.get("quantity_kg"),
                    "weight_kg": bag.get("weight_kg") or bag.get("quantity_kg"),
                }
                for bag in matched
                if bag.get("bag_code")
            ]
            lot_row.metadata_ = {
                **(lot_row.metadata_ if isinstance(lot_row.metadata_, dict) else {}),
                "source_inward_order_id": str(source_inward_id),
                "source_inward_order_code": inward.order_code,
                **({"crusher_grade": grade_label} if grade_label else {}),
                **({"crusher_outward_bags": outward_bags} if outward_bags else {}),
                **(
                    {"crusher_bag_code": outward_bags[0]["bag_code"]}
                    if outward_bags
                    else {}
                ),
            }
            flag_modified(lot_row, "metadata_")
            created_lots.append(lot_out)
            released_lot_rows.append(
                {
                    "lot_code": lot_out.lot_code,
                    "quantity_kg": str(lot_qty),
                    "production_order_code": po_row.production_order_code,
                    **({"crusher_grade": grade_label} if grade_label else {}),
                    "outward_bag_codes": [bag["bag_code"] for bag in outward_bags],
                }
            )
        meta["released_lots"] = released_lot_rows
        meta["last_release_lot_count"] = len(created_lots)
        inward.metadata_ = meta
        flag_modified(inward, "metadata_")
        repo.db.commit()
        return AcMakeToStockCreateResponse(
            order=order_out,
            line=finished_line_out,
            production_order=po_out,
            production_lot=created_lots[0] if created_lots else None,
            production_lots=created_lots,
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


_KILN_READING_META = "kiln_parameter_readings"


def _kiln_reading_values(payload: AcKilnParametersCreate) -> dict[str, Any]:
    return {
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


def _parse_reading_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def list_kiln_parameters(
    db: Session, tenant: TenantContext, lot_code: Optional[str] = None
) -> List[AcKilnParameterReadingOut]:
    out: list[AcKilnParameterReadingOut] = []
    for kiln in _list_tenant_kiln_resources(db, tenant):
        meta = kiln.metadata_ if isinstance(kiln.metadata_, dict) else {}
        for row in meta.get(_KILN_READING_META) or []:
            if not isinstance(row, dict):
                continue
            out.append(
                AcKilnParameterReadingOut(
                    reading_id=str(row.get("reading_id") or uuid4()),
                    kiln_resource_code=str(row.get("kiln_resource_code") or kiln.resource_code),
                    recorded_at=_parse_reading_at(row.get("recorded_at")),
                    readings=row.get("readings") if isinstance(row.get("readings"), dict) else {},
                )
            )
    if not out:
        rows = _repo(db, tenant).query(OperationExecution).order_by(OperationExecution.created_at.desc()).all()
        if lot_code:
            lot = _repo(db, tenant).get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
            rows = [r for r in rows if r.production_lot_id == lot.production_lot_id]
        for row in rows:
            meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
            readings = {
                k: meta[k]
                for k in (
                    "zone1_temp_c",
                    "zone2_temp_c",
                    "steam_flow_kg_h",
                    "residence_time_min",
                    "o2_pct",
                    "kiln_temp_c",
                    "pressure_bar",
                )
                if meta.get(k) is not None
            }
            if not readings:
                continue
            out.append(
                AcKilnParameterReadingOut(
                    reading_id=str(row.execution_id),
                    kiln_resource_code=str(meta.get("kiln_resource_code") or ""),
                    recorded_at=row.created_at or datetime.now(timezone.utc),
                    readings=readings,
                )
            )
    out.sort(key=lambda row: row.recorded_at, reverse=True)
    return out


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


def lookup_material_trace(db: Session, tenant: TenantContext, query: str):
    from app.services.industry.activated_carbon import material_trace as ac_material_trace

    return ac_material_trace.lookup_material_trace(db, tenant, query)


def list_material_trace_options(
    db: Session, tenant: TenantContext, kind: str, month: str | None = None
):
    from app.services.industry.activated_carbon import material_trace as ac_material_trace

    return ac_material_trace.list_material_trace_options(db, tenant, kind, month)


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
    obsolete_product_ids = {
        t.product_id for t in raw_material_types if t.is_obsolete
    }
    active_type_ids = {
        t.product_id for t in raw_material_types if not t.is_obsolete
    }
    raw_products = [
        p
        for p in products
        if (
            (p.product_type or "").upper() == "RAW_MATERIAL"
            or (p.product_code or "").upper().startswith("RAW-")
        )
        and (p.status or "").upper() != "OBSOLETE"
        and p.product_id not in obsolete_product_ids
    ]
    if active_type_ids:
        raw_products = [p for p in raw_products if p.product_id in active_type_ids]
    elif not raw_products:
        raw_products = products
    finished_ids: list = []
    seen_finished: set = set()
    for typed in raw_material_types:
        if typed.is_obsolete or not typed.finished_product_id:
            continue
        fid = typed.finished_product_id
        if fid in seen_finished:
            continue
        seen_finished.add(fid)
        finished_ids.append(fid)
    by_product_id = {p.product_id: p for p in products}
    finished_products = [by_product_id[fid] for fid in finished_ids if fid in by_product_id]
    if len(finished_products) < len(finished_ids):
        repo_lookup = _repo(db, tenant)
        for fid in finished_ids:
            if fid in by_product_id:
                continue
            row = repo_lookup.get_by_pk(Product, Product.product_id, fid)
            if row is not None:
                finished_products.append(row)
    if not finished_products:
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
    from app.services.industry.activated_carbon.station_machines import ensure_station_machines
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
    from app.services.industry.activated_carbon import process_rules as ac_process_rules
    from app.services.industry.activated_carbon import mesh_grade as ac_mesh_grade

    ensure_station_machines(db, tenant)
    ac_plant_equipment.ensure_plant_equipment(db, tenant)
    ac_process_rules.ensure_process_rules(db, tenant)
    ac_process_rules.ensure_inbound_catalog(db, tenant)
    ac_mesh_grade.ensure_mesh_grade_map(db, tenant)
    repo = _repo(db, tenant)
    all_resource_rows = repo.query(Resource).order_by(Resource.resource_code).all()
    destoner_rows = [
        _resource_out(r) for r in ac_plant_equipment.list_destoner_resources(db, tenant)
    ]
    destoner_ids = {r.resource_id for r in ac_plant_equipment.list_destoner_resources(db, tenant)}
    machine_rows = [
        _resource_out(r)
        for r in all_resource_rows
        if (r.resource_type or "").upper() == "MACHINE"
        and not (r.resource_code or "").upper().startswith("RES-KILN")
        and str((r.metadata_ or {}).get("role") or "").lower() != "post_activation"
        and str((r.metadata_ or {}).get("station") or "").lower() != "fg_qc"
        and "finished goods" not in (r.resource_name or "").lower()
        and r.resource_id not in destoner_ids
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
        destoners=destoner_rows,
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
    if rtype == "MACHINE":
        station = str(getattr(payload, "station", None) or "").strip().lower()
        if station:
            meta["station"] = station
        unit_count = getattr(payload, "unit_count", None)
        if unit_count is not None:
            meta["unit_count"] = int(unit_count)
        from app.services.industry.activated_carbon.station_machines import (
            DEFAULT_MONTHLY_CAPACITY_KG,
        )

        monthly = getattr(payload, "monthly_capacity_kg", None)
        meta["monthly_capacity_kg"] = (
            int(monthly) if monthly is not None else DEFAULT_MONTHLY_CAPACITY_KG
        )

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
        station=meta.get("station"),
        unit_count=meta.get("unit_count"),
        monthly_capacity_kg=meta.get("monthly_capacity_kg"),
        equipment_id=equipment_id,
        equipment_code=equipment_code,
        equipment_name=equipment_name,
    )


def update_plant_resource(
    db: Session, tenant: TenantContext, resource_id: UUID, payload: ResourceUpdate
) -> ResourceOut:
    repo = _repo(db, tenant)
    resource = repo.get_by_pk(Resource, Resource.resource_id, resource_id)
    meta = dict(resource.metadata_ if isinstance(resource.metadata_, dict) else {})
    if payload.monthly_capacity_kg is not None:
        meta["monthly_capacity_kg"] = int(payload.monthly_capacity_kg)
    if payload.unit_count is not None:
        meta["unit_count"] = int(payload.unit_count)
    resource.metadata_ = meta
    flag_modified(resource, "metadata_")
    repo.commit_refresh(resource)
    return _resource_out(resource)


def create_destoner(
    db: Session, tenant: TenantContext, payload: AcDestonerCreate
) -> ResourceOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    kwargs: dict[str, Any] = {"name": payload.destoner_name}
    if payload.unit_count is not None:
        kwargs["unit_count"] = int(payload.unit_count)
    if payload.monthly_capacity_kg is not None:
        kwargs["monthly_capacity_kg"] = int(payload.monthly_capacity_kg)
    resource = ac_plant_equipment.create_destoner_resource(db, tenant, **kwargs)
    if payload.status:
        resource.status = payload.status
        _repo(db, tenant).commit_refresh(resource)
    return _resource_out(resource)


def get_destoner_daily_ctc(db: Session, tenant: TenantContext) -> AcDestonerDailyCtcOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    from app.services.industry.activated_carbon import mesh_grade as ac_mesh_grade

    today = plant_today(tenant.timezone)
    destoners = _list_destoner_resources(db, tenant)
    plan = ac_plant_equipment.tenant_daily_ctc_plan(db, tenant, today)
    catalog = ac_mesh_grade.get_mesh_grade_map(db, tenant)
    return AcDestonerDailyCtcOut(
        assignment_date=str(today),
        destoners=[
            AcDestonerDailyCtcRow(
                resource_code=str(row.resource_code or ""),
                resource_name=str(row.resource_name or row.resource_code or ""),
                **ac_plant_equipment.destoner_plan_meta(row, plan, today),
            )
            for row in destoners
        ],
        mesh_configurations=catalog.get("configurations") or [],
    )


def save_destoner_daily_ctc(
    db: Session,
    tenant: TenantContext,
    payload: AcDestonerDailyCtcSave,
    user: Any = None,
) -> AcDestonerDailyCtcOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    destoners = {str(row.resource_code or ""): row for row in _list_destoner_resources(db, tenant)}
    today = plant_today(tenant.timezone)
    user_id = None
    if user is not None:
        user_id = getattr(user, "username", None) or getattr(user, "email", None) or getattr(
            user, "sub", None
        )
    assignments: dict[str, dict] = {}
    for row in payload.destoners or []:
        code = (row.resource_code or "").strip()
        machine = destoners.get(code)
        if machine is None:
            raise ValidationError(f"Destoner '{code}' was not found.")
        rounded = None
        if row.assigned_ctc not in (None, ""):
            rounded = ac_process_rules.round_ctc(row.assigned_ctc)
            if rounded is None:
                raise ValidationError(f"CTC for {code} must be a number.")
        ac_plant_equipment.set_destoner_daily_ctc(
            machine,
            str(rounded) if rounded is not None else None,
            mesh=None,
            user_id=str(user_id) if user_id else None,
            today=today,
        )
        if rounded is not None:
            assignments[code] = {
                "ctc": str(rounded),
                "mesh": None,
                "by": str(user_id) if user_id else None,
            }
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:destoner:{machine.resource_code}",
                    predicate_uri="urn:nyra:predicate:captures",
                    object_uri="urn:nyra:ac:parameter:CTC",
                    object_literal=str(rounded),
                    object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                    source_table="cfg.tenant",
                    source_id=tenant.tenant_id,
                ),
            )
    ac_plant_equipment.save_tenant_daily_ctc_plan(
        db, tenant, assignments, today=today
    )
    _repo(db, tenant).db.commit()
    return get_destoner_daily_ctc(db, tenant)


def get_kiln_setpoints(db: Session, tenant: TenantContext) -> AcKilnSetpointsOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
    from app.services.industry.activated_carbon.kiln_parameters_catalog import (
        list_kiln_parameter_definitions,
    )
    from app.services.industry.activated_carbon.station_machines import monthly_capacity_kg_of

    plan = ac_plant_equipment.kiln_setpoint_plan(db, tenant)
    definitions = list_kiln_parameter_definitions(db, tenant)
    rows: list[AcKilnSetpointRow] = []
    for kiln in _list_tenant_kiln_resources(db, tenant):
        code = str(kiln.resource_code or "")
        entry = plan.get(code) or {}
        params = dict(entry.get("parameters") or {})
        monthly = monthly_capacity_kg_of(kiln)
        residence = ac_plant_equipment.residence_minutes_for(plan, code)
        rows.append(
            AcKilnSetpointRow(
                resource_code=code,
                resource_name=str(kiln.resource_name or code),
                monthly_capacity_kg=monthly,
                residence_time_min=residence,
                designed_monthly_kg=ac_plant_equipment.designed_monthly_kg_for_residence(
                    monthly, residence
                ),
                parameters=params,
                updated_at=entry.get("updated_at"),
                updated_by=entry.get("by"),
            )
        )
    return AcKilnSetpointsOut(
        reference_residence_min=ac_plant_equipment.REFERENCE_RESIDENCE_MIN,
        definitions=definitions,
        kilns=rows,
        history=[
            AcKilnSetpointChange(
                kiln_resource_code=str(item.get("kiln_resource_code") or ""),
                at=item.get("at"),
                by=item.get("by"),
                parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
            )
            for item in ac_plant_equipment.kiln_setpoint_history(db, tenant)
            if item.get("kiln_resource_code")
        ],
    )


def save_kiln_setpoints(
    db: Session,
    tenant: TenantContext,
    payload: AcKilnSetpointsSave,
    user: Any = None,
) -> AcKilnSetpointsOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
    from app.services.industry.activated_carbon.kiln_parameters_catalog import (
        list_kiln_parameter_definitions,
    )

    kilns = {str(row.resource_code or ""): row for row in _list_tenant_kiln_resources(db, tenant)}
    allowed = {row.key for row in list_kiln_parameter_definitions(db, tenant)}
    user_id = None
    if user is not None:
        user_id = getattr(user, "username", None) or getattr(user, "email", None) or getattr(
            user, "sub", None
        )
    assignments: dict[str, dict] = {}
    for row in payload.kilns or []:
        code = (row.resource_code or "").strip()
        machine = kilns.get(code)
        if machine is None:
            raise ValidationError(f"Kiln '{code}' was not found.")
        cleaned: dict[str, float] = {}
        for key, value in (row.parameters or {}).items():
            if key not in allowed:
                raise ValidationError(f"Unknown kiln parameter '{key}'.")
            if value in (None, ""):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValidationError(f"{key} for {code} must be a number.") from None
            if number < 0:
                raise ValidationError(f"{key} for {code} cannot be negative.")
            if key == "residence_time_min" and number <= 0:
                raise ValidationError(f"Residence time for {code} must be greater than 0.")
            cleaned[key] = number
        assignments[code] = {
            "parameters": cleaned,
            "by": str(user_id) if user_id else None,
        }
        for key, number in cleaned.items():
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:kiln:{code}",
                    predicate_uri="urn:nyra:predicate:captures",
                    object_uri=f"urn:nyra:ac:parameter:{key}",
                    object_literal=str(number),
                    object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                    source_table="cfg.tenant",
                    source_id=tenant.tenant_id,
                ),
            )
    ac_plant_equipment.save_kiln_setpoint_plan(db, tenant, assignments)
    _repo(db, tenant).db.commit()
    return get_kiln_setpoints(db, tenant)


def _dispatch_kg_by_work_order(db: Session, tenant: TenantContext) -> dict[str, Decimal]:
    from app.services.mes_core.dispatch_workflow import dispatch_quantity_kg

    totals: dict[str, Decimal] = {}
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(QualityCheck.check_type == "DISPATCH")
        .all()
    )
    for row in rows:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        code = str(meta.get("work_order_code") or "").strip()
        if not code:
            continue
        totals[code] = totals.get(code, Decimal("0")) + dispatch_quantity_kg(meta)
    return totals


def _work_order_out(
    row: dict,
    dispatched_kg: Decimal | None = None,
    output_kg: Decimal | None = None,
) -> AcWorkOrderOut:
    ordered = Decimal(str(row.get("quantity_kg") or 0))
    dispatched = (
        Decimal(str(dispatched_kg))
        if dispatched_kg is not None
        else Decimal(str(row.get("dispatched_kg") or 0))
    )
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    pending = ac_work_orders.pending_dispatch_kg(ordered, dispatched)
    outputted = (
        Decimal(str(output_kg))
        if output_kg is not None
        else Decimal(str(row.get("output_kg") or 0))
    )
    return AcWorkOrderOut(
        work_order_code=str(row.get("work_order_code") or ""),
        grade=row.get("grade"),
        ctc=row.get("ctc"),
        quantity_kg=ordered,
        loaded_kg=Decimal(str(row.get("loaded_kg") or 0)),
        output_kg=outputted,
        fulfilled_kg=Decimal(str(row.get("fulfilled_kg") or 0)),
        dispatched_kg=dispatched,
        pending_kg=pending,
        status=str(row.get("status") or "OPEN"),
        created_at=row.get("created_at"),
        created_by=row.get("created_by"),
        kiln_resource_code=row.get("kiln_resource_code"),
    )


def list_activation_work_orders(db: Session, tenant: TenantContext) -> AcWorkOrderListOut:
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    dispatched = _dispatch_kg_by_work_order(db, tenant)
    output_kg = ac_work_orders.kiln_output_kg_by_work_order(db, tenant)
    return AcWorkOrderListOut(
        work_orders=[
            _work_order_out(
                row,
                dispatched.get(str(row.get("work_order_code") or ""), Decimal("0")),
                output_kg.get(str(row.get("work_order_code") or ""), Decimal("0")),
            )
            for row in ac_work_orders.list_work_orders(db, tenant)
        ],
        grades=ac_work_orders.kiln_feed_grade_options(db, tenant),
    )


def create_activation_work_order(
    db: Session,
    tenant: TenantContext,
    payload: AcWorkOrderCreate,
    user: Any = None,
) -> AcWorkOrderOut:
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    user_id = None
    if user is not None:
        user_id = getattr(user, "username", None) or getattr(user, "email", None) or getattr(
            user, "sub", None
        )
    row = ac_work_orders.create_work_order(
        db,
        tenant,
        grade=payload.grade,
        ctc=payload.ctc,
        quantity_kg=payload.quantity_kg,
        user_id=str(user_id) if user_id else None,
    )
    _stage_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=f"urn:nyra:ac:workOrder:{row['work_order_code']}",
            predicate_uri="urn:nyra:predicate:captures",
            object_uri="urn:nyra:ac:parameter:CTC",
            object_literal=str(row.get("ctc") or ""),
            object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
            source_table="cfg.tenant",
            source_id=tenant.tenant_id,
        ),
    )
    _repo(db, tenant).db.commit()
    return _work_order_out(row)


def delete_activation_work_order(
    db: Session, tenant: TenantContext, work_order_code: str
) -> AcWorkOrderOut:
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    return _work_order_out(ac_work_orders.delete_work_order(db, tenant, work_order_code))


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

    from app.services.industry.activated_carbon.station_machines import (
        DEFAULT_MONTHLY_CAPACITY_KG,
        monthly_capacity_kg_of,
    )

    monthly = (
        int(payload.monthly_capacity_kg)
        if payload.monthly_capacity_kg is not None
        else DEFAULT_MONTHLY_CAPACITY_KG
    )
    resource = repo.add(
        Resource(
            resource_code=resource_code,
            resource_name=name,
            resource_type="MACHINE",
            status=payload.status or "ACTIVE",
            metadata_={
                "role": "kiln",
                "equipment_class": "KILN",
                "monthly_capacity_kg": monthly,
            },
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
        monthly_capacity_kg=monthly_capacity_kg_of(resource),
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
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    repo = _repo(db, tenant)
    kiln_rows = _list_tenant_kiln_resources(db, tenant)
    kiln_setpoints = ac_plant_equipment.kiln_setpoint_plan(db, tenant)
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
                lot_meta = candidate.metadata_ if isinstance(candidate.metadata_, dict) else {}
                if lot_meta.get("kiln_resource_code") == code:
                    lot = candidate
                    break
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
        last_at = latest.created_at if latest else None
        if lot:
            lot_status = (lot.status or "").upper()
            lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
            live = str(lot_meta.get("kiln_live_status") or "").upper()
            charged = lot_meta.get("charged_at")
            if charged and last_at is None:
                try:
                    last_at = datetime.fromisoformat(str(charged).replace("Z", "+00:00"))
                except ValueError:
                    last_at = None
            ex_status = (latest.status or "").upper() if latest else ""
            ex_step = str((latest.metadata_ or {}).get("process_step") or "").upper() if latest else ""
            if lot_status == "IN_PROGRESS":
                if live == "IN_KILN" or ex_step in {"KILN_FEED", "ACTIVATION"} or ex_status not in (
                    "COMPLETED",
                    "CLOSED",
                ):
                    status = "RUNNING"
                elif ex_status == "COMPLETED":
                    status = "COOLING"
            elif lot_status in {"COMPLETED", "QC_PENDING"} and ex_status == "COMPLETED":
                status = "COOLING"
        feed_events: list[dict] = []
        kiln_meta = kiln.metadata_ if isinstance(kiln.metadata_, dict) else {}
        raw_events = kiln_meta.get("kiln_feed_events")
        if isinstance(raw_events, list):
            feed_events.extend(ev for ev in raw_events if isinstance(ev, dict))
        for candidate in lots_by_id.values():
            cand_meta = candidate.metadata_ if isinstance(candidate.metadata_, dict) else {}
            if cand_meta.get("kiln_resource_code") != code:
                continue
            cand_events = cand_meta.get("kiln_feed_events")
            if isinstance(cand_events, list) and cand_events:
                feed_events.extend(ev for ev in cand_events if isinstance(ev, dict))
            elif cand_meta.get("charged_at"):
                feed_events.append(
                    {
                        "lot_code": candidate.lot_code,
                        "bag_code": cand_meta.get("crusher_bag_code"),
                        "kg": float(candidate.lot_quantity or 0),
                        "loaded_at": cand_meta.get("charged_at"),
                        "kiln_resource_code": code,
                    }
                )
        seen: set[str] = set()
        unique_events: list[dict] = []
        for ev in sorted(feed_events, key=lambda row: str(row.get("loaded_at") or "")):
            key = f"{ev.get('lot_code')}|{ev.get('bag_code') or ''}|{ev.get('loaded_at')}"
            if key in seen:
                continue
            seen.add(key)
            unique_events.append(ev)
        loaded_kg = sum(Decimal(str(ev.get("kg") or 0)) for ev in unique_events)
        monthly = ac_station_machines.monthly_capacity_kg_of(kiln)
        residence = ac_plant_equipment.residence_minutes_for(kiln_setpoints, code)
        rows.append(
            AcKilnStatusOut(
                resource_code=code,
                resource_name=kiln.resource_name or code,
                status=status,
                active_lot_code=lot.lot_code if lot else None,
                active_lot_kg=loaded_kg if unique_events else (lot.lot_quantity if lot else None),
                loaded_kg=loaded_kg if unique_events else None,
                monthly_capacity_kg=monthly,
                residence_time_min=residence,
                designed_monthly_kg=ac_plant_equipment.designed_monthly_kg_for_residence(
                    monthly, residence
                ),
                feed_events=unique_events,
                last_reading_at=last_at,
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
        return "Awaiting kiln feed"
    return lot_status or "Unknown"


def _dispatched_kg_by_lot_id(db: Session, tenant: TenantContext) -> dict:
    from app.services.mes_core.dispatch_workflow import dispatch_quantity_kg

    totals: dict = {}
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(QualityCheck.check_type == "DISPATCH")
        .all()
    )
    for row in rows:
        lot_id = row.production_lot_id
        if lot_id is None:
            continue
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        totals[lot_id] = totals.get(lot_id, Decimal("0")) + dispatch_quantity_kg(meta)
    return totals


def _in_stock_kg_by_lot_code(db: Session, tenant: TenantContext) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for bag in ac_post_activation.list_available_in_stock_bags(db, tenant):
        code = str(bag.get("lot_code") or "").strip()
        if not code:
            continue
        totals[code] = totals.get(code, Decimal("0")) + Decimal(str(bag.get("remaining_kg") or 0))
    return totals


def _lot_line_rows(db: Session, tenant: TenantContext) -> list[AcLotLineOut]:
    repo = _repo(db, tenant)
    dispatched_by_lot = _dispatched_kg_by_lot_id(db, tenant)
    in_stock_by_lot = _in_stock_kg_by_lot_code(db, tenant)
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
                dispatched_kg=dispatched_by_lot.get(lot.production_lot_id, Decimal("0")),
                in_stock_kg=in_stock_by_lot.get(lot.lot_code, Decimal("0")),
                status=lot.status,
                feasibility_status=feas,
                pipeline_stage=stage,
                is_in_progress=in_progress,
            )
        )
    return rows


def list_open_production_lots(
    db: Session, tenant: TenantContext
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
        if st in _OPEN_LOT_STATUSES or routing_complete:
            continue

        po = po_by_id.get(lot.production_order_id)
        order_code = line_to_order.get(po.order_line_id) if po else None
        feas = feas_by_lot.get(lot.production_lot_id)
        stage = _lot_pipeline_stage(
            lot.status, feas, exec_done=done, exec_total=total
        )
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
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
                kiln_resource_code=lot_meta.get("kiln_resource_code"),
                charged_at=lot_meta.get("charged_at"),
                kiln_live_status=lot_meta.get("kiln_live_status"),
                kiln_feed_events=lot_meta.get("kiln_feed_events")
                if isinstance(lot_meta.get("kiln_feed_events"), list)
                else [],
                kiln_loaded_kg=lot_meta.get("kiln_loaded_kg"),
                metadata=lot_meta or None,
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
        "Awaiting kiln feed": 5,
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
        elif count_key in {"EXECUTION", "ROUTING"} and count > 0:
            status = "done" if count_key == "ROUTING" else "active"
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
                    work_order_code=meta.get("work_order_code"),
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
        utilization_rag=ac_isa95_rag.get_utilization_rag(db, tenant),
    )


def _routing_operation_for_lot(
    db: Session, tenant: TenantContext, production_lot_id, process_step: str
) -> RoutingOperation:
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(ProductionLot, ProductionLot.production_lot_id, production_lot_id)
    _product, routing, ops, _qty = ac_lot_routing.load_ac_lot_routing(db, tenant, lot)
    if not routing:
        raise ValueError(f"No active routing for lot {lot.lot_code}")

    target_code = f"OP-{process_step}"
    for op in ops:
        meta = op.metadata_ if isinstance(op.metadata_, dict) else {}
        if meta.get("process_step") == process_step or op.operation_code == target_code:
            return op
    raise ValueError(f"No routing operation for process step {process_step}")


def _stage_triple(db: Session, tenant: TenantContext, payload: TripleCreate) -> None:
    """Queue a triple in the current transaction — no per-row commit."""
    repo = _repo(db, tenant)
    repo.add(
        TripleStoreStaging(
            subject_uri=payload.subject_uri,
            predicate_uri=payload.predicate_uri,
            object_uri=payload.object_uri,
            object_literal=payload.object_literal,
            object_datatype=payload.object_datatype,
            source_table=payload.source_table,
            source_id=payload.source_id,
            export_status=payload.export_status,
        )
    )


def _create_process_execution(
    db: Session,
    tenant: TenantContext,
    production_lot_id,
    process_step: str,
    metadata: dict,
    *,
    commit: bool = True,
) -> OperationExecutionOut:
    repo = _repo(db, tenant)
    op = _routing_operation_for_lot(db, tenant, production_lot_id, process_step)
    code = resolve_ac_business_code(db, provided=None, entity="ac_operation_execution")
    recorded_step = (metadata.get("process_step") or process_step).strip()
    row = repo.add(
        OperationExecution(
            execution_code=code,
            production_lot_id=production_lot_id,
            routing_operation_id=op.routing_operation_id,
            status="COMPLETED",
            metadata_={
                **metadata,
                "process_step": recorded_step,
                "industry_template_code": tenant.industry_template_code,
            },
        )
    )
    if commit:
        out = OperationExecutionOut.model_validate(repo.commit_refresh(row))
    else:
        repo.db.flush()
        repo.db.refresh(row)
        out = OperationExecutionOut.model_validate(row)
    if kiln_release_step(recorded_step):
        lot = repo.get_by_pk(
            ProductionLot, ProductionLot.production_lot_id, production_lot_id
        )
        release_lot_kiln_if_claimed(db, tenant, lot)
        if commit:
            repo.db.commit()
    return out


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
        elif finished_line is None:
            finished_line = line

    if raw_line is None:
        raise ValidationError(
            "Inward order has no raw material line — cannot create a production order."
        )

    finished = _resolve_finished_product_for_raw(
        db, tenant, raw_line.product_id
    )
    raw_po_meta = ac_lot_routing.production_order_meta_for_raw(
        db, tenant, raw_line.product_id
    )

    for line in lines:
        product = products.get(line.product_id)
        if product and line.product_id == finished.product_id:
            finished_line = line
            break

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
            **raw_po_meta,
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
    po_out = mes_core_entities.create_production_order(
        db,
        tenant,
        ProductionOrderCreate(
            production_order_code=po_code,
            order_line_id=finished_line_id,
            planned_quantity=po_qty,
            status="PLANNED",
        ),
    )
    po_row = repo.get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, po_out.production_order_id
    )
    po_row.metadata_ = {
        **(po_row.metadata_ if isinstance(po_row.metadata_, dict) else {}),
        **raw_po_meta,
        "source_inward_order_id": str(order_id),
    }
    repo.db.commit()
    repo.db.refresh(po_row)
    return mes_core_entities.get_production_order(db, tenant, po_row.production_order_id)


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


def sync_ac_production_order_material_links(
    db: Session, tenant: TenantContext
) -> List[dict]:
    """Stamp raw_product_id / routing_id on existing production orders from inward links."""
    repo = _repo(db, tenant)
    products = {p.product_id: p for p in repo.query(Product).all()}
    updated: List[dict] = []

    for po in repo.query(ProductionOrder).all():
        po_meta = po.metadata_ if isinstance(po.metadata_, dict) else {}
        raw_product_id = _uuid_or_none(po_meta.get("raw_product_id"))

        if not raw_product_id:
            inward_id = _uuid_or_none(po_meta.get("source_inward_order_id"))
            if inward_id:
                for ol in (
                    repo.query(CustomerOrderLine)
                    .filter(CustomerOrderLine.order_id == inward_id)
                    .all()
                ):
                    product = products.get(ol.product_id)
                    if product and _is_raw_product(product):
                        raw_product_id = product.product_id
                        break
                if not raw_product_id:
                    inward = repo.get_by_pk(
                        CustomerOrder, CustomerOrder.customer_order_id, inward_id
                    )
                    imeta = inward.metadata_ if isinstance(inward.metadata_, dict) else {}
                    raw_product_id = _uuid_or_none(imeta.get("raw_product_id"))

        if not raw_product_id:
            continue

        stamp = ac_lot_routing.production_order_meta_for_raw(
            db, tenant, raw_product_id
        )
        merged = {**po_meta, **stamp}
        if merged == po_meta:
            continue

        po.metadata_ = merged
        flag_modified(po, "metadata_")
        updated.append(
            {
                "production_order_code": po.production_order_code,
                "raw_product_id": str(raw_product_id),
                "routing_id": stamp.get("routing_id"),
            }
        )

    if updated:
        repo.db.commit()
    return updated


def create_raw_material_inward(
    db: Session, tenant: TenantContext, payload: AcRawMaterialInwardCreate
) -> AcRawMaterialInwardCreateResponse:
    sync_ac_sequences(db, tenant.tenant_id)
    if not (payload.dc_number or "").strip():
        raise ValidationError("DC number is required on gate receipt.")
    if payload.supplier_weight_kg is None:
        raise ValidationError("Supplier weight (KG) is required on gate receipt.")
    if payload.our_weight_kg is None and payload.quantity is None:
        raise ValidationError("Our weight (KG) is required on gate receipt.")
    if payload.our_weight_kg is not None:
        payload.quantity = payload.our_weight_kg
    if payload.quantity is None or payload.quantity <= 0:
        raise ValidationError("Our weight (KG) must be greater than zero.")
    if payload.supplier_weight_kg is not None and payload.quantity > payload.supplier_weight_kg:
        raise ValidationError("Our weight cannot be greater than the supplier weight.")
    ac_raw_material_types.assert_raw_material_active_for_inward(
        db, tenant, payload.product_id
    )
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
    inward_receipt: dict = {}
    if payload.dc_number:
        inward_receipt["dc_number"] = payload.dc_number.strip()
    if payload.supplier_weight_kg is not None:
        inward_receipt["supplier_weight_kg"] = str(payload.supplier_weight_kg)
    if getattr(payload, "our_weight_kg", None) is not None:
        inward_receipt["our_weight_kg"] = str(payload.our_weight_kg)
    if payload.supplier_value_inr is not None:
        inward_receipt["supplier_value_inr"] = str(payload.supplier_value_inr)
    if getattr(payload, "our_value_inr", None) is not None:
        inward_receipt["our_value_inr"] = str(payload.our_value_inr)
    order_row.metadata_ = {
        **(order_row.metadata_ if isinstance(order_row.metadata_, dict) else {}),
        "flow": "RAW_MATERIAL_INWARD",
        "raw_product_id": str(payload.product_id),
    }
    if inward_receipt:
        order_row.metadata_["inward_receipt"] = inward_receipt
    repo.db.commit()
    repo.db.refresh(order_row)
    supplier = repo.get_by_pk(Supplier, Supplier.supplier_id, payload.supplier_id)
    _stage_inward_receipt_triples(
        db,
        tenant,
        order_row,
        supplier_code=supplier.supplier_code,
        inward_receipt=inward_receipt,
        received_qty_kg=payload.quantity,
    )
    repo.db.commit()
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
        bags=[],
    )


def _debit_note_for_order(
    db: Session,
    tenant: TenantContext,
    meta: dict,
    *,
    our_weight_fallback=None,
    supplier_name=None,
    supplier_code=None,
):
    from app.services.industry.activated_carbon import debit_notes as ac_debit_notes
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    return ac_debit_notes.evaluate_debit_note(
        meta,
        ac_process_rules.get_process_rules(db, tenant),
        our_weight_fallback=our_weight_fallback,
        supplier_name=supplier_name,
        supplier_code=supplier_code,
    )


def raise_inward_debit_note(
    db: Session,
    tenant: TenantContext,
    customer_order_id,
    payload,
    *,
    raised_by: str | None = None,
):
    from app.services.industry.activated_carbon import debit_notes as ac_debit_notes

    ac_debit_notes.raise_debit_note(
        db, tenant, customer_order_id, payload, raised_by=raised_by
    )
    order = _repo(db, tenant).get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, customer_order_id
    )
    return _raw_material_qc_from_order(db, tenant, order)


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
    initial_qc = meta.get("initial_qc") if isinstance(meta.get("initial_qc"), dict) else {}
    supplier = None
    if getattr(order, "supplier_id", None):
        try:
            supplier = repo.get_by_pk(Supplier, Supplier.supplier_id, order.supplier_id)
        except NotFoundError:
            supplier = None
    supplier_code = getattr(supplier, "supplier_code", None)
    supplier_name = getattr(supplier, "supplier_name", None)
    qc = meta.get("raw_material_qc") if isinstance(meta.get("raw_material_qc"), dict) else {}
    crush = (
        meta.get("raw_material_crush")
        if isinstance(meta.get("raw_material_crush"), dict)
        else {}
    )

    raw_type_id = _uuid_or_none(meta.get("raw_product_id")) or product.product_id
    inbound_steps: list[AcInboundStepStatusOut] = []
    inbound_prep_complete = True
    next_inbound_step = None
    next_inbound_operation_code = None
    try:
        material_type = ac_raw_material_types.get_raw_material_type(
            db, tenant, raw_type_id
        )
        inbound_steps = ac_inbound_execution.build_inbound_step_statuses(
            material_type, meta
        )
        inbound_prep_complete = ac_inbound_execution.mandatory_inbound_prep_complete(
            material_type, meta
        )
        next_inbound_step = ac_inbound_execution.next_inbound_process_step(
            material_type, meta
        )
        next_inbound_operation_code = ac_inbound_execution.next_inbound_operation_code(
            material_type, meta
        )
    except NotFoundError:
        from types import SimpleNamespace
        from app.services.industry.activated_carbon import process_rules as ac_process_rules

        material_type = SimpleNamespace(
            inbound_operations=ac_process_rules.normalized_inbound_operations([])
        )
        inbound_steps = ac_inbound_execution.build_inbound_step_statuses(
            material_type, meta
        )
        inbound_prep_complete = ac_inbound_execution.mandatory_inbound_prep_complete(
            material_type, meta
        )
        next_inbound_step = ac_inbound_execution.next_inbound_process_step(
            material_type, meta
        )
        next_inbound_operation_code = ac_inbound_execution.next_inbound_operation_code(
            material_type, meta
        )

    return AcRawMaterialQcOut(
        customer_order_id=order.customer_order_id,
        order_code=order.order_code,
        product_code=product.product_code,
        product_name=product.product_name,
        quantity=line.quantity,
        uom=line.uom,
        our_weight_kg=(
            Decimal(str(meta.get("inward_receipt", {}).get("our_weight_kg")))
            if isinstance(meta.get("inward_receipt"), dict)
            and meta["inward_receipt"].get("our_weight_kg") is not None
            else line.quantity
        ),
        moisture_pct=initial_qc.get("moisture_pct") or qc.get("moisture_pct"),
        dust_pct=initial_qc.get("dust_pct"),
        volatility=initial_qc.get("volatility"),
        ash_pct=qc.get("ash_pct"),
        foreign_matter_pct=qc.get("foreign_matter_pct"),
        stones_kg=qc.get("stones_kg"),
        unburnt_kg=qc.get("unburnt_kg"),
        minus20_kg=qc.get("minus20_kg"),
        operator_remarks=qc.get("operator_remarks"),
        qc_status=qc.get("qc_status") or "PENDING",
        qc_at=qc.get("qc_at"),
        crush_status=crush.get("status") or "PENDING",
        crush_at=crush.get("completed_at"),
        raw_material_type_id=raw_type_id,
        inbound_steps=inbound_steps,
        inbound_prep_complete=inbound_prep_complete,
        next_inbound_step=next_inbound_step,
        next_inbound_operation_code=next_inbound_operation_code,
        lab_denied=ac_inbound_workflow.lab_denied(meta),
        lab_remarks=(
            (meta.get("initial_qc") or {}).get("remarks")
            if isinstance(meta.get("initial_qc"), dict)
            else None
        )
        or qc.get("operator_remarks"),
        supplier_id=order.supplier_id,
        supplier_code=supplier_code,
        supplier_name=supplier_name,
        debit_note=_debit_note_for_order(
            db,
            tenant,
            meta,
            our_weight_fallback=line.quantity,
            supplier_name=supplier_name,
            supplier_code=supplier_code,
        ),
    )


def _stage_inward_receipt_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    *,
    supplier_code: str,
    inward_receipt: dict,
    received_qty_kg: Decimal,
) -> None:
    """Stage supplier receipt + DC details into kg.triple_store_staging (triplet ontology)."""
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    supplier_uri = f"urn:nyra:ac:supplier:{supplier_code}"
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=supplier_uri,
            predicate_uri="urn:nyra:predicate:supplies",
            object_uri=subject,
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:captures",
            object_uri="urn:nyra:ac:parameter:RECEIVED_QTY_KG",
            object_literal=str(received_qty_kg),
            object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    string_params = (
        ("dc_number", "urn:nyra:ac:parameter:DC_NUMBER"),
    )
    for field, param_uri in string_params:
        value = inward_receipt.get(field)
        if not value:
            continue
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=param_uri,
                object_literal=str(value),
                object_datatype="http://www.w3.org/2001/XMLSchema#string",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )
    decimal_params = (
        ("supplier_weight_kg", "urn:nyra:ac:parameter:SUPPLIER_WEIGHT_KG"),
        ("our_weight_kg", "urn:nyra:ac:parameter:OUR_WEIGHT_KG"),
        ("supplier_value_inr", "urn:nyra:ac:parameter:SUPPLIER_VALUE_INR"),
        ("our_value_inr", "urn:nyra:ac:parameter:OUR_VALUE_INR"),
    )
    for field, param_uri in decimal_params:
        value = inward_receipt.get(field)
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


def _stage_crushing_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    crush_payload: dict,
) -> None:
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    object_uri = f"urn:nyra:ac:crushing:{order.order_code}"
    source_id = order.customer_order_id
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:captures",
            object_uri=object_uri,
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    for field, param_uri in (
        ("input_lump_size_mm", "urn:nyra:ac:parameter:INPUT_LUMP_SIZE_MM"),
        ("target_output_size_mm", "urn:nyra:ac:parameter:TARGET_OUTPUT_SIZE_MM"),
        ("crush_output_kg", "urn:nyra:ac:parameter:CRUSH_OUTPUT_KG"),
        ("crush_yield_pct", "urn:nyra:ac:parameter:CRUSH_YIELD_PCT"),
        ("moisture_after_pct", "urn:nyra:ac:parameter:MOISTURE_AFTER_CRUSH_PCT"),
        ("dust_generation_pct", "urn:nyra:ac:parameter:DUST_GENERATION_PCT"),
    ):
        value = crush_payload.get(field)
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


def list_inbound_execution(
    db: Session, tenant: TenantContext
) -> List[AcInboundExecutionOut]:
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    ac_process_rules.ensure_inbound_catalog(db, tenant)
    rows = list_raw_material_qc(db, tenant)
    return [AcInboundExecutionOut.model_validate(row.model_dump()) for row in rows]


def complete_inbound_execution_step(
    db: Session, tenant: TenantContext, payload: AcInboundStepCompleteCreate
) -> AcInboundExecutionOut:
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, payload.customer_order_id
    )
    row = _raw_material_qc_from_order(db, tenant, order)
    if not row:
        raise NotFoundError(
            f"Order '{order.order_code}' has no raw material line for inbound execution"
        )
    product_id = row.raw_material_type_id
    if not product_id:
        raise ValidationError("Inward order is missing raw material type reference.")
    ac_inbound_execution.complete_inbound_step(
        db, tenant, payload, product_id=product_id
    )
    refreshed = _raw_material_qc_from_order(db, tenant, order)
    assert refreshed is not None
    return AcInboundExecutionOut.model_validate(refreshed.model_dump())


def list_raw_material_crushing(
    db: Session, tenant: TenantContext
) -> List[AcRawMaterialCrushOut]:
    rows = list_raw_material_qc(db, tenant)
    return [AcRawMaterialCrushOut.model_validate(row.model_dump()) for row in rows]


def create_raw_material_crush(
    db: Session, tenant: TenantContext, payload: AcRawMaterialCrushCreate
) -> AcRawMaterialCrushOut:
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, payload.customer_order_id
    )
    existing = _raw_material_qc_from_order(db, tenant, order)
    if not existing:
        raise NotFoundError(
            f"Order '{order.order_code}' has no raw material line for crushing"
        )
    product_id = existing.raw_material_type_id
    if not product_id:
        raise ValidationError("Inward order is missing raw material type reference.")

    parameters = {
        k: v
        for k, v in {
            "input_lump_size_mm": payload.input_lump_size_mm,
            "target_output_size_mm": payload.target_output_size_mm,
            "throughput_kg_h": payload.throughput_kg_h,
            "crush_output_kg": payload.crush_output_kg,
            "crush_yield_pct": payload.crush_yield_pct,
            "moisture_before_pct": payload.moisture_before_pct,
            "moisture_after_pct": payload.moisture_after_pct,
            "dust_generation_pct": payload.dust_generation_pct,
            "crusher_id": payload.crusher_id,
            "operator_remarks": payload.operator_remarks,
        }.items()
        if v is not None
    }
    ac_inbound_execution.complete_inbound_step(
        db,
        tenant,
        AcInboundStepCompleteCreate(
            customer_order_id=payload.customer_order_id,
            process_step="CRUSHING",
            parameters=parameters,
        ),
        product_id=product_id,
        allow_unconfigured=True,
    )
    row = _raw_material_qc_from_order(db, tenant, order)
    assert row is not None
    return AcRawMaterialCrushOut.model_validate(row.model_dump())


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

    raw_type_id = _uuid_or_none(meta.get("raw_product_id"))
    if raw_type_id:
        try:
            material_type = ac_raw_material_types.get_raw_material_type(
                db, tenant, raw_type_id
            )
            if not ac_inbound_execution.mandatory_inbound_prep_complete(
                material_type, meta
            ):
                pending = ac_inbound_execution.next_inbound_process_step(
                    material_type, meta
                )
                raise ValidationError(
                    f"Order '{order.order_code}' requires inbound prep before QC — "
                    f"complete step '{pending or 'inbound prep'}' on Inbound Execution first."
                )
        except NotFoundError:
            pass
    elif meta.get("raw_material_crush"):
        crush = meta.get("raw_material_crush") if isinstance(meta.get("raw_material_crush"), dict) else {}
        if crush.get("status") != "COMPLETED":
            raise ValidationError(
                f"Order '{order.order_code}' requires crushing / sizing before QC — "
                "complete the Crushing step first."
            )

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


def _kiln_feed_event_list(meta: dict) -> list[dict]:
    raw = meta.get("kiln_feed_events")
    return [dict(row) for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _assert_bag_not_already_in_kiln(db: Session, tenant: TenantContext, bag_code: Optional[str]) -> None:
    """A bag already charged to any kiln cannot be entered again."""
    code = (bag_code or "").strip()
    if not code:
        return
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    for row in ac_plant_equipment.ensure_six_kilns(db, tenant):
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        for event in _kiln_feed_event_list(meta):
            if str(event.get("bag_code") or "") == code:
                raise WorkflowError(f"Bag '{code}' is already loaded into the kiln")


def _next_kiln_feed_bag(meta: dict, requested_bag: Optional[str] = None) -> Optional[dict]:
    bags = meta.get("crusher_outward_bags")
    bags = [row for row in bags if isinstance(row, dict)] if isinstance(bags, list) else []
    bags = [row for row in bags if ac_inbound_workflow._is_kiln_feed_bag(row)]
    fed = {
        str(ev.get("bag_code"))
        for ev in _kiln_feed_event_list(meta)
        if ev.get("bag_code")
    }
    if requested_bag:
        code = requested_bag.strip()
        if code in fed:
            raise WorkflowError(f"Bag '{code}' is already loaded into the kiln")
        for bag in bags:
            if str(bag.get("bag_code") or "") == code:
                return bag
        raise ValidationError(
            f"Bag '{code}' is not available for kiln feed. Unburnt and Stones stay off the kiln."
        )
    for bag in bags:
        code = str(bag.get("bag_code") or "")
        if code and code not in fed:
            return bag
    return None


def _kiln_resource(db: Session, tenant: TenantContext, kiln_code: str) -> Optional[Resource]:
    """Kilns are plant-wide. Match the code shown on Execution, not one workspace."""
    code = (kiln_code or "").strip()
    if not code:
        return None
    return (
        _tenant_resources(db, tenant)
        .filter(Resource.resource_code == code)
        .first()
    )


def _append_kiln_resource_feed(
    db: Session, tenant: TenantContext, kiln_code: str, event: dict
) -> None:
    resource = _kiln_resource(db, tenant, kiln_code)
    if resource is None:
        return
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    events = _kiln_feed_event_list(meta)
    events.append(event)
    lot_codes = [str(c) for c in (meta.get("active_lot_codes") or []) if c]
    if event.get("lot_code") and event["lot_code"] not in lot_codes:
        lot_codes.append(event["lot_code"])
    resource.metadata_ = {
        **meta,
        "kiln_feed_events": events,
        "active_lot_codes": lot_codes,
        "active_lot_code": event.get("lot_code") or meta.get("active_lot_code"),
        "current_work_order_code": event.get("work_order_code")
        or meta.get("current_work_order_code"),
        "loaded_kg": str(sum(Decimal(str(ev.get("kg") or 0)) for ev in events)),
    }
    flag_modified(resource, "metadata_")


def _kiln_output_prefix(resource: Resource) -> str:
    return kiln_output_id_prefix(resource.resource_name or "", resource.resource_code or "")


def _merged_kiln_feed_meta(db: Session, tenant: TenantContext, resource: Resource) -> dict:
    """Kiln resource feed plus any loads stored only on the production lot."""
    meta = dict(resource.metadata_ if isinstance(resource.metadata_, dict) else {})
    code = str(resource.resource_code or "")
    merged: list[dict] = []
    seen: set[tuple] = set()

    def _take(event: dict, lot_code: str | None = None) -> None:
        row = dict(event)
        if lot_code and not row.get("lot_code"):
            row["lot_code"] = lot_code
        if code and not row.get("kiln_resource_code"):
            row["kiln_resource_code"] = code
        key = (
            str(row.get("lot_code") or ""),
            str(row.get("bag_code") or ""),
            str(row.get("loaded_at") or ""),
            str(row.get("work_order_code") or ""),
            str(row.get("kg") or row.get("quantity_kg") or ""),
        )
        if key in seen:
            return
        seen.add(key)
        merged.append(row)

    for event in _kiln_feed_event_list(meta):
        _take(event)
    for lot in _repo(db, tenant).query(ProductionLot).all():
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        if str(lot_meta.get("kiln_resource_code") or "") != code:
            continue
        for event in _kiln_feed_event_list(lot_meta):
            event_kiln = str(event.get("kiln_resource_code") or code)
            if event_kiln != code:
                continue
            _take(event, lot.lot_code)
    meta["kiln_feed_events"] = merged
    return meta


def list_kiln_output_bags(
    db: Session, tenant: TenantContext, kiln_resource_code: str
) -> AcKilnOutputListOut:
    resource = _kiln_resource(db, tenant, kiln_resource_code)
    if resource is None:
        raise ValidationError(f"Kiln '{kiln_resource_code}' was not found")
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    raw = meta.get("kiln_output_bags")
    bags = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    current = (ac_plant_equipment.kiln_setpoint_plan(db, tenant).get(kiln_resource_code) or {})
    items = [
        AcKilnOutputBagOut(
            bag_code=str(row.get("bag_code") or ""),
            quantity_kg=Decimal(str(row.get("quantity_kg") or 0)),
            kiln_resource_code=kiln_resource_code,
            lot_code=row.get("lot_code"),
            work_order_code=row.get("work_order_code"),
            created_at=row.get("created_at"),
            created_by=row.get("created_by"),
            kiln_parameters=row.get("kiln_parameters") if isinstance(row.get("kiln_parameters"), dict) else {},
            kiln_parameters_at=row.get("kiln_parameters_at"),
        )
        for row in bags
        if row.get("bag_code")
    ]
    total = sum((row.quantity_kg for row in items), Decimal("0"))
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    balance = _merged_kiln_feed_meta(db, tenant, resource)
    loaded = ac_work_orders.kiln_total_feed_kg(balance)
    remaining = ac_work_orders.kiln_remaining_output_kg(balance)
    work_order_code = ac_work_orders.kiln_current_work_order_code(balance)
    feed_events = [
        AcKilnFeedChipOut(
            bag_code=str(event.get("bag_code") or "") or None,
            kg=Decimal(str(event.get("kg") or event.get("quantity_kg") or 0)),
            loaded_at=event.get("loaded_at"),
            lot_code=event.get("lot_code"),
            work_order_code=event.get("work_order_code"),
            kiln_resource_code=str(event.get("kiln_resource_code") or kiln_resource_code),
        )
        for event in (balance.get("kiln_feed_events") or [])
        if isinstance(event, dict)
    ]
    return AcKilnOutputListOut(
        kiln_resource_code=kiln_resource_code,
        current_parameters=current.get("parameters") if isinstance(current.get("parameters"), dict) else {},
        current_parameters_at=current.get("updated_at"),
        bags=items,
        bag_count=len(items),
        total_kg=total,
        loaded_kg=loaded,
        remaining_kg=remaining,
        work_order_code=work_order_code,
        feed_events=feed_events,
    )


def _session_actor(user: Any) -> str | None:
    if user is None:
        return None
    raw = getattr(user, "username", None) or getattr(user, "email", None)
    text = str(raw or "").strip()
    return text or None


def create_kiln_output_bag(
    db: Session, tenant: TenantContext, payload: AcKilnOutputBagCreate, user: Any = None
) -> AcKilnOutputBagOut:
    repo = _repo(db, tenant)
    kiln_code = payload.kiln_resource_code.strip()
    resource = _kiln_resource(db, tenant, kiln_code)
    if resource is None:
        raise ValidationError(f"Kiln '{kiln_code}' was not found")
    stored = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    raw = stored.get("kiln_output_bags")
    bags = [dict(row) for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    balance = _merged_kiln_feed_meta(db, tenant, resource)
    now_iso = datetime.now(timezone.utc).isoformat()
    lot_code = (payload.lot_code or balance.get("active_lot_code") or "").strip() or None
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    ac_work_orders.assert_kiln_output_within_load(balance, payload.quantity_kg)
    work_order_code = ac_work_orders.kiln_output_target_work_order(balance, payload.quantity_kg)
    if not work_order_code:
        raise ValidationError("Load a work order on this kiln before adding kiln output.")
    work_order_ctc = None
    try:
        work_order_ctc = ac_work_orders.get_work_order(db, tenant, work_order_code).get("ctc")
    except ValidationError:
        work_order_ctc = None
    prefix = _kiln_output_prefix(resource)
    bag_code = next_kiln_output_bag_code(repo.db, prefix, tenant.timezone)
    balance["kiln_output_seq"] = int(bag_code.rsplit("_", 1)[-1])
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    setpoint = ac_plant_equipment.kiln_setpoint_plan(db, tenant).get(kiln_code) or {}
    kiln_parameters = setpoint.get("parameters") if isinstance(setpoint.get("parameters"), dict) else {}
    row = {
        "bag_code": bag_code,
        "quantity_kg": float(payload.quantity_kg),
        "kiln_resource_code": kiln_code,
        "lot_code": lot_code,
        "work_order_code": work_order_code,
        "work_order_ctc": work_order_ctc,
        "created_at": now_iso,
        "created_by": _session_actor(user),
        "kiln_parameters": kiln_parameters,
        "kiln_parameters_at": setpoint.get("updated_at"),
    }
    bags.append(row)
    resource.metadata_ = {**balance, "kiln_output_bags": bags}
    flag_modified(resource, "metadata_")
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=f"urn:nyra:ac:kilnOutBag:{bag_code}",
            predicate_uri="urn:nyra:predicate:contained_in",
            object_uri=f"urn:nyra:ac:kiln:{kiln_code}",
            source_table="cfg.resource",
            source_id=resource.resource_id,
        ),
    )
    if lot_code:
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:ac:kilnOutBag:{bag_code}",
                predicate_uri="urn:nyra:predicate:generatedFrom",
                object_uri=f"urn:nyra:ac:lot:{lot_code}",
                source_table="cfg.resource",
                source_id=resource.resource_id,
            ),
        )
    repo.db.commit()
    return AcKilnOutputBagOut(
        bag_code=bag_code,
        quantity_kg=payload.quantity_kg,
        kiln_resource_code=kiln_code,
        lot_code=lot_code,
        work_order_code=work_order_code,
        created_at=now_iso,
        created_by=_session_actor(user),
        kiln_parameters=kiln_parameters,
        kiln_parameters_at=setpoint.get("updated_at"),
    )


def _kiln_out_qc_param_defs(db: Session, tenant: TenantContext) -> list[dict]:
    repo = _repo(db, tenant)
    try:
        raw = repo.get_by_code(Product, Product.product_code, "RAW-COCO-SHELL")
    except Exception:
        return []
    meta = raw.metadata_ if isinstance(getattr(raw, "metadata_", None), dict) else {}
    return [row for row in (meta.get("process_parameters") or []) if isinstance(row, dict)]


def _iter_kiln_output_resources(db: Session, tenant: TenantContext, kiln_resource_code: Optional[str] = None):
    wanted = (kiln_resource_code or "").strip()
    resources = (
        _tenant_resources(db, tenant).filter(Resource.resource_code == wanted).all()
        if wanted
        else _list_tenant_kiln_resources(db, tenant)
    )
    for resource in resources:
        meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
        raw = meta.get("kiln_output_bags")
        bags = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
        if bags or (wanted and (resource.resource_code or "") == wanted):
            yield resource, meta, bags


def list_kiln_output_qc_bags(
    db: Session, tenant: TenantContext, kiln_resource_code: Optional[str] = None
) -> list[AcKilnOutputBagQcOut]:
    rows: list[AcKilnOutputBagQcOut] = []
    for resource, _meta, bags in _iter_kiln_output_resources(db, tenant, kiln_resource_code):
        for bag in bags:
            code = str(bag.get("bag_code") or "")
            if not code:
                continue
            qc = bag.get("kiln_output_qc") if isinstance(bag.get("kiln_output_qc"), dict) else {}
            rows.append(
                AcKilnOutputBagQcOut(
                    bag_code=code,
                    kiln_resource_code=str(resource.resource_code or bag.get("kiln_resource_code") or ""),
                    quantity_kg=Decimal(str(bag.get("quantity_kg") or 0)),
                    lot_code=bag.get("lot_code"),
                    work_order_code=bag.get("work_order_code"),
                    work_order_ctc=bag.get("work_order_ctc"),
                    ctc_match=bag.get("work_order_ctc_match"),
                    created_at=bag.get("created_at"),
                    created_by=bag.get("created_by"),
                    user_id=qc.get("user_id"),
                    values=qc.get("values") if isinstance(qc.get("values"), dict) else {},
                    saved_at=qc.get("saved_at"),
                )
            )
    rows.sort(key=lambda row: str(row.created_at or ""), reverse=True)
    return rows


def save_kiln_output_bag_qc(
    db: Session, tenant: TenantContext, payload: AcKilnOutputBagQcCreate
) -> AcKilnOutputBagQcOut:
    from app.services.industry.activated_carbon import triplet_capture as ac_triples

    repo = _repo(db, tenant)
    code = (payload.bag_code or "").strip()
    if not code:
        raise ValidationError("Bag number is required.")
    found = None
    for resource, meta, bags in _iter_kiln_output_resources(db, tenant, payload.kiln_resource_code):
        for bag in bags:
            if str(bag.get("bag_code") or "") == code:
                found = (resource, meta, bags, bag)
                break
        if found:
            break
    if found is None:
        raise ValidationError(f"Kiln output bag '{code}' was not found.")
    resource, meta, bags, bag = found
    existing = bag.get("kiln_output_qc") if isinstance(bag.get("kiln_output_qc"), dict) else None
    if existing and existing.get("saved_at"):
        raise ValidationError(
            f"Kiln output quality for bag '{code}' is already saved and cannot be changed."
        )
    values: dict[str, Any] = {}
    for key, raw in (payload.values or {}).items():
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        values[str(key)] = text
    now = datetime.now(timezone.utc).isoformat()
    from app.services.industry.activated_carbon import process_rules as ac_process_rules
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    wo_code = str(bag.get("work_order_code") or "").strip() or None
    wo_ctc = bag.get("work_order_ctc")
    if wo_code and wo_ctc in (None, ""):
        try:
            wo_ctc = ac_work_orders.get_work_order(db, tenant, wo_code).get("ctc")
        except ValidationError:
            wo_ctc = None
    actual_ctc = ac_process_rules.ctc_from_values(values)
    ctc_match = bool(wo_code and ac_work_orders.work_order_ctc_matches(wo_ctc, actual_ctc))
    qc = {
        "values": values,
        "user_id": (payload.user_id or "").strip() or None,
        "saved_at": now,
        "lot_code": (payload.lot_code or bag.get("lot_code") or "").strip() or None,
        "work_order_ctc_match": ctc_match,
    }
    bag["kiln_output_qc"] = qc
    bag["work_order_ctc_match"] = ctc_match
    if wo_ctc not in (None, ""):
        bag["work_order_ctc"] = wo_ctc
    resource.metadata_ = {**meta, "kiln_output_bags": bags}
    flag_modified(resource, "metadata_")
    if wo_code:
        ac_work_orders.record_work_order_output(
            db,
            tenant,
            work_order_code=wo_code,
            quantity_kg=bag.get("quantity_kg") or 0,
            bag_code=code,
            kiln_resource_code=str(resource.resource_code or ""),
            ctc_match=ctc_match,
            commit=False,
        )
    ac_triples.stage_captures_for_values(
        db,
        tenant,
        subject_uri=f"urn:nyra:ac:kilnOutBag:{code}",
        values=values,
        source_table="cfg.resource",
        source_id=resource.resource_id,
        param_defs=_kiln_out_qc_param_defs(db, tenant),
        process_step="ACTIVATION",
        used_at="execution",
        operation_code="OP-KILN-OUT-QC",
    )
    repo.db.commit()
    return AcKilnOutputBagQcOut(
        bag_code=code,
        kiln_resource_code=str(resource.resource_code or ""),
        quantity_kg=Decimal(str(bag.get("quantity_kg") or 0)),
        lot_code=bag.get("lot_code"),
        work_order_code=wo_code,
        work_order_ctc=str(wo_ctc) if wo_ctc not in (None, "") else None,
        ctc_match=ctc_match,
        created_at=bag.get("created_at"),
        created_by=bag.get("created_by"),
        user_id=qc.get("user_id"),
        values=values,
        saved_at=now,
    )


DESTONING_LOADER_CAPACITY = 6


def _ensure_destoner_resource(db: Session, tenant: TenantContext) -> Resource:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    destoners = ac_plant_equipment.ensure_four_destoners(db, tenant)
    if not destoners:
        raise ValidationError("No destoner machines are registered.")
    return destoners[0]


def _list_destoner_resources(db: Session, tenant: TenantContext) -> list[Resource]:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    return ac_plant_equipment.ensure_four_destoners(db, tenant)


def _resolve_destoner(
    db: Session, tenant: TenantContext, resource_code: Optional[str] = None
) -> Resource:
    destoners = _list_destoner_resources(db, tenant)
    wanted = (resource_code or "").strip()
    if wanted:
        found = next((row for row in destoners if str(row.resource_code or "") == wanted), None)
        if found is None:
            raise ValidationError(f"Destoner '{wanted}' was not found.")
        return found
    return destoners[0]


def _destoner_loader_capacity(resource: Resource) -> int:
    from app.services.industry.activated_carbon.station_machines import _unit_count

    return max(_unit_count(resource), 1)


def _kiln_output_qc_saved(bag: dict) -> bool:
    qc = bag.get("kiln_output_qc") if isinstance(bag.get("kiln_output_qc"), dict) else {}
    return bool(qc.get("saved_at"))


def _kiln_bag_ctc(bag: dict) -> Any:
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    qc = bag.get("kiln_output_qc") if isinstance(bag.get("kiln_output_qc"), dict) else {}
    values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
    rounded = ac_process_rules.round_ctc(ac_process_rules.ctc_from_values(values))
    return str(rounded) if rounded is not None else None


def _destoner_load_ctc(loaded: list[dict]) -> Any:
    for row in loaded:
        raw = row.get("ctc")
        if raw not in (None, ""):
            return raw
    return None


def _destoning_qc_saved(bag: dict) -> bool:
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    return bool(qc.get("saved_at"))


def _destoning_qc_values(bag: dict) -> dict:
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
    return values


def _destoning_bag_ctc(bag: dict) -> Any:
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    rounded = ac_process_rules.round_ctc(bag.get("ctc"))
    if rounded is not None:
        return str(rounded)
    values = _destoning_qc_values(bag)
    rounded = ac_process_rules.round_ctc(ac_process_rules.ctc_from_values(values))
    return str(rounded) if rounded is not None else None


def _is_destoning_rework_bag(bag: dict) -> bool:
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    if not _destoning_qc_saved(bag):
        return False
    values = _destoning_qc_values(bag)
    dest = (
        values.get("deston_qc_destination")
        or bag.get("deston_qc_destination")
        or bag.get("destination")
        or ""
    )
    if ac_process_rules.is_destoning_rework_destination(dest):
        return True
    try:
        return bool(ac_process_rules.destoning_stones_present(
            ac_process_rules.destoning_stones_from_values(values)
        ))
    except ValidationError:
        return False


def _destoning_kiln_letter(resource: Resource, bag_code: str) -> str:
    code = str(bag_code or "").upper()
    prefix = re.match(r"^(K[A-F]|KO[A-F])(?:_|-|\d)", code)
    if prefix:
        return prefix.group(1)[-1]
    blob = " ".join(
        [
            str(getattr(resource, "resource_name", "") or ""),
            str(getattr(resource, "resource_code", "") or ""),
        ]
    ).upper()
    match = re.search(r"KILN[-_\s]*([A-F])\b", blob)
    if match:
        return match.group(1)
    return "A"


def _deston_bag(row: dict, kiln_code: Optional[str] = None) -> AcDestoningBagOut:
    return AcDestoningBagOut(
        bag_code=str(row.get("bag_code") or ""),
        quantity_kg=Decimal(str(row.get("quantity_kg") or 0)),
        kiln_resource_code=kiln_code or row.get("kiln_resource_code"),
        lot_code=row.get("lot_code"),
        work_order_code=str(row.get("work_order_code") or "").strip() or None,
        created_at=row.get("created_at"),
        created_by=row.get("created_by"),
        input_bag_codes=[str(c) for c in (row.get("input_bag_codes") or []) if c],
        destoner_resource_code=row.get("destoner_resource_code"),
        ctc=str(row.get("ctc")) if row.get("ctc") not in (None, "") else None,
        kiln_output_qc_saved=bool(row.get("kiln_output_qc_saved")),
    )


def _destoning_lists(meta: dict) -> tuple[list[dict], list[dict]]:
    loaded = [dict(row) for row in (meta.get("destoning_loaded_bags") or []) if isinstance(row, dict)]
    outputs = [dict(row) for row in (meta.get("destoning_output_bags") or []) if isinstance(row, dict)]
    return loaded, outputs


def _destoning_events(meta: dict) -> list[dict]:
    return [dict(row) for row in (meta.get("destoning_load_events") or []) if isinstance(row, dict)]


def _deston_output_kg_against_load(loaded: list[dict], outputs: list[dict]) -> Decimal:
    """Kilograms already bagged from the bags sitting on the destoner now."""
    codes = {str(row.get("bag_code") or "") for row in loaded if row.get("bag_code")}
    if not codes:
        return Decimal("0")
    total = Decimal("0")
    for row in outputs:
        inputs = {str(code) for code in (row.get("input_bag_codes") or []) if code}
        if inputs & codes:
            total += Decimal(str(row.get("quantity_kg") or 0))
    return total


def _deston_event(row: dict) -> AcDestoningLoadEventOut:
    return AcDestoningLoadEventOut(
        bag_code=row.get("bag_code"),
        lot_code=row.get("lot_code"),
        kg=Decimal(str(row.get("kg") or row.get("quantity_kg") or 0)),
        loaded_at=row.get("loaded_at") or row.get("created_at"),
        kiln_resource_code=row.get("kiln_resource_code"),
        destoner_resource_code=row.get("destoner_resource_code"),
    )


def _destoning_state_from(
    db: Session, tenant: TenantContext, destoner: Resource
) -> AcDestoningStateOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    destoners = _list_destoner_resources(db, tenant)
    ctc_plan = ac_plant_equipment.tenant_daily_ctc_plan(db, tenant)
    selected = destoner or destoners[0]
    loaded_all: list[dict] = []
    outputs_all: list[dict] = []
    events_all: list[dict] = []
    destoner_outs: list[AcDestonerMachineOut] = []
    loaded_codes: set[str] = set()
    consumed: set[str] = set()
    for machine in destoners:
        meta = machine.metadata_ if isinstance(machine.metadata_, dict) else {}
        loaded, outputs = _destoning_lists(meta)
        events = _destoning_events(meta)
        if not events:
            events = [
                {
                    "bag_code": row.get("bag_code"),
                    "lot_code": row.get("lot_code"),
                    "kg": row.get("quantity_kg") or 0,
                    "loaded_at": row.get("loaded_at") or row.get("created_at"),
                    "kiln_resource_code": row.get("kiln_resource_code"),
                    "destoner_resource_code": machine.resource_code,
                }
                for row in loaded
                if row.get("bag_code")
            ]
        for row in loaded:
            row.setdefault("destoner_resource_code", machine.resource_code)
            if row.get("bag_code"):
                loaded_codes.add(str(row.get("bag_code")))
        for out in outputs:
            out.setdefault("destoner_resource_code", machine.resource_code)
            for code in out.get("input_bag_codes") or []:
                if code:
                    consumed.add(str(code))
        loaded_kg = sum((Decimal(str(row.get("quantity_kg") or 0)) for row in loaded), Decimal("0"))
        plan = ac_plant_equipment.destoner_plan_meta(machine, ctc_plan, plant_today(tenant.timezone))
        destoner_outs.append(
            AcDestonerMachineOut(
                resource_code=str(machine.resource_code or ""),
                resource_name=str(machine.resource_name or machine.resource_code or ""),
                loaded=[_deston_bag(row) for row in loaded if row.get("bag_code")],
                loaded_kg=loaded_kg,
                loader_count=len(loaded),
                loader_capacity=_destoner_loader_capacity(machine),
                load_ctc=str(_destoner_load_ctc(loaded)) if _destoner_load_ctc(loaded) not in (None, "") else None,
                assigned_ctc=plan.get("assigned_ctc"),
                assigned_mesh=plan.get("assigned_mesh"),
                assigned_date=plan.get("assigned_date"),
                output_bags=[_deston_bag(row) for row in outputs if row.get("bag_code")],
                load_events=[_deston_event(row) for row in events if row.get("bag_code") or row.get("loaded_at")],
            )
        )
        if str(machine.resource_code or "") == str(selected.resource_code or ""):
            loaded_all = loaded
            outputs_all = outputs
            events_all = events
    seen_bags: set[str] = set()
    grouped: dict[str, AcDestoningKilnGroupOut] = {
        letter: AcDestoningKilnGroupOut(
            kiln_resource_code=f"KILN-{letter}",
            kiln_name=f"Kiln {letter}",
            bags=[],
        )
        for letter in ("A", "B", "C", "D", "E", "F")
    }
    for resource, _meta, bags in _iter_kiln_output_resources(db, tenant):
        for bag in bags:
            code = str(bag.get("bag_code") or "")
            if not code or code in seen_bags or code in loaded_codes or code in consumed:
                continue
            if not _kiln_output_qc_saved(bag):
                continue
            seen_bags.add(code)
            letter = _destoning_kiln_letter(resource, code)
            if letter not in grouped:
                grouped[letter] = AcDestoningKilnGroupOut(
                    kiln_resource_code=f"KILN-{letter}",
                    kiln_name=f"Kiln {letter}",
                    bags=[],
                )
            grouped[letter].bags.append(
                _deston_bag(
                    {
                        **bag,
                        "ctc": _kiln_bag_ctc(bag),
                        "kiln_output_qc_saved": True,
                    },
                    resource.resource_code,
                )
            )
    kiln_groups = [grouped[key] for key in ("A", "B", "C", "D", "E", "F")]
    rework_bags: list[AcDestoningBagOut] = []
    for machine in destoners:
        meta = machine.metadata_ if isinstance(machine.metadata_, dict) else {}
        _loaded, outputs = _destoning_lists(meta)
        for bag in outputs:
            code = str(bag.get("bag_code") or "")
            if not code or code in seen_bags or code in loaded_codes or code in consumed:
                continue
            if not _is_destoning_rework_bag(bag):
                continue
            seen_bags.add(code)
            rework_bags.append(
                _deston_bag(
                    {
                        **bag,
                        "ctc": _destoning_bag_ctc(bag),
                        "kiln_output_qc_saved": True,
                    },
                    bag.get("kiln_resource_code") or machine.resource_code,
                )
            )
    if rework_bags:
        kiln_groups.append(
            AcDestoningKilnGroupOut(
                kiln_resource_code="DESTONING-REWORK",
                kiln_name="Destoning rework",
                bags=rework_bags,
            )
        )
    loaded_kg = sum((Decimal(str(row.get("quantity_kg") or 0)) for row in loaded_all), Decimal("0"))
    return AcDestoningStateOut(
        kilns=kiln_groups,
        loaded=[_deston_bag(row) for row in loaded_all if row.get("bag_code")],
        loaded_kg=loaded_kg,
        loader_count=len(loaded_all),
        loader_capacity=_destoner_loader_capacity(selected),
        output_bags=[_deston_bag(row) for row in outputs_all if row.get("bag_code")],
        load_events=[_deston_event(row) for row in events_all if row.get("bag_code") or row.get("loaded_at")],
        destoners=destoner_outs,
        selected_destoner_code=str(selected.resource_code or "") or None,
    )


def get_destoning_state(db: Session, tenant: TenantContext) -> AcDestoningStateOut:
    destoner = _ensure_destoner_resource(db, tenant)
    return _destoning_state_from(db, tenant, destoner)


def load_destoning_bag(
    db: Session, tenant: TenantContext, payload: AcDestoningLoadCreate
) -> AcDestoningStateOut:
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    repo = _repo(db, tenant)
    destoner = _resolve_destoner(db, tenant, payload.destoner_resource_code)
    dest_meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
    loaded, outputs = _destoning_lists(dest_meta)
    events = _destoning_events(dest_meta)
    code = (payload.bag_code or "").strip()
    if not code:
        raise ValidationError("Bag number is required.")
    if any(str(row.get("bag_code") or "") == code for row in loaded):
        raise ValidationError(f"Bag '{code}' is already on the de-stoner.")
    deston_capacity = _destoner_loader_capacity(destoner)
    if len(loaded) >= deston_capacity:
        raise ValidationError(f"De-stoner loader is full ({deston_capacity} bags).")
    consumed = {
        str(c)
        for machine in _list_destoner_resources(db, tenant)
        for out in _destoning_lists(
            machine.metadata_ if isinstance(machine.metadata_, dict) else {}
        )[1]
        for c in (out.get("input_bag_codes") or [])
        if c
    }
    if code in consumed:
        raise ValidationError(f"Bag '{code}' has already been destoned.")
    found = None
    rework = False
    for resource, _meta, bags in _iter_kiln_output_resources(db, tenant):
        for bag in bags:
            if str(bag.get("bag_code") or "") == code:
                found = (resource, bag)
                break
        if found:
            break
    if found is None:
        for machine in _list_destoner_resources(db, tenant):
            meta = machine.metadata_ if isinstance(machine.metadata_, dict) else {}
            _loaded_rows, output_rows = _destoning_lists(meta)
            match = next(
                (row for row in output_rows if str(row.get("bag_code") or "") == code),
                None,
            )
            if match is not None and _is_destoning_rework_bag(match):
                found = (machine, match)
                rework = True
                break
    if found is None:
        raise ValidationError(
            f"Bag '{code}' was not found among kiln output or destoning rework bags."
        )
    resource, bag = found
    rules = ac_process_rules.get_process_rules(db, tenant)
    if (
        not rework
        and rules.get("kiln_output_qc_required_for_destoning")
        and not _kiln_output_qc_saved(bag)
    ):
        raise ValidationError(
            f"Save kiln output QC for bag '{code}' before destoning load."
        )
    incoming_ctc = _destoning_bag_ctc(bag) if rework else _kiln_bag_ctc(bag)
    decimals = int(rules.get("ctc_decimals") or 1)
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    assigned = ac_plant_equipment.destoner_plan_meta(
        destoner,
        ac_plant_equipment.tenant_daily_ctc_plan(db, tenant),
        plant_today(tenant.timezone),
    ).get("assigned_ctc")
    if rework and incoming_ctc in (None, ""):
        incoming_ctc = assigned
    ac_process_rules.assert_destoner_plan_ctc(
        assigned,
        incoming_ctc,
        decimals=decimals,
    )
    ac_process_rules.assert_same_ctc(
        _destoner_load_ctc(loaded),
        incoming_ctc,
        decimals=decimals,
        missing_blocks=bool(rules.get("ctc_missing_blocks_load", True)),
    )
    now = datetime.now(timezone.utc).isoformat()
    loaded.append(
        {
            "bag_code": code,
            "quantity_kg": float(bag.get("quantity_kg") or 0),
            "kiln_resource_code": bag.get("kiln_resource_code") or resource.resource_code,
            "lot_code": bag.get("lot_code"),
            "work_order_code": bag.get("work_order_code"),
            "created_at": bag.get("created_at"),
            "loaded_at": now,
            "ctc": incoming_ctc if incoming_ctc not in (None, "") else None,
            "destoner_resource_code": destoner.resource_code,
            "rework": rework,
        }
    )
    events.append(
        {
            "bag_code": code,
            "lot_code": bag.get("lot_code"),
            "kg": float(bag.get("quantity_kg") or 0),
            "loaded_at": now,
            "kiln_resource_code": bag.get("kiln_resource_code") or resource.resource_code,
            "destoner_resource_code": destoner.resource_code,
        }
    )
    destoner.metadata_ = {
        **dest_meta,
        "destoning_loaded_bags": loaded,
        "destoning_output_bags": outputs,
        "destoning_load_events": events,
    }
    flag_modified(destoner, "metadata_")
    _stage_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=(
                f"urn:nyra:ac:destonBag:{code}" if rework else f"urn:nyra:ac:kilnOutBag:{code}"
            ),
            predicate_uri="urn:nyra:predicate:usedEquipment",
            object_uri=f"urn:nyra:ac:destoner:{destoner.resource_code}",
            source_table="cfg.resource",
            source_id=destoner.resource_id,
        ),
    )
    if incoming_ctc not in (None, ""):
        _stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=(
                    f"urn:nyra:ac:destonBag:{code}" if rework else f"urn:nyra:ac:kilnOutBag:{code}"
                ),
                predicate_uri="urn:nyra:predicate:captures",
                object_uri="urn:nyra:ac:parameter:CTC",
                object_literal=str(incoming_ctc),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="cfg.resource",
                source_id=destoner.resource_id,
            ),
        )
    repo.db.commit()
    repo.db.refresh(destoner)
    return _destoning_state_from(db, tenant, destoner)


def unload_destoning_bag(
    db: Session, tenant: TenantContext, payload: AcDestoningLoadCreate
) -> AcDestoningStateOut:
    repo = _repo(db, tenant)
    destoner = _resolve_destoner(db, tenant, payload.destoner_resource_code)
    if payload.destoner_resource_code is None:
        for machine in _list_destoner_resources(db, tenant):
            meta = machine.metadata_ if isinstance(machine.metadata_, dict) else {}
            loaded, _outputs = _destoning_lists(meta)
            if any(str(row.get("bag_code") or "") == (payload.bag_code or "").strip() for row in loaded):
                destoner = machine
                break
    dest_meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
    loaded, outputs = _destoning_lists(dest_meta)
    events = _destoning_events(dest_meta)
    code = (payload.bag_code or "").strip()
    next_loaded = [row for row in loaded if str(row.get("bag_code") or "") != code]
    if len(next_loaded) == len(loaded):
        raise ValidationError(f"Bag '{code}' is not on the de-stoner.")
    next_events = list(events)
    for index in range(len(next_events) - 1, -1, -1):
        if str(next_events[index].get("bag_code") or "") == code:
            next_events.pop(index)
            break
    destoner.metadata_ = {
        **dest_meta,
        "destoning_loaded_bags": next_loaded,
        "destoning_output_bags": outputs,
        "destoning_load_events": next_events,
    }
    flag_modified(destoner, "metadata_")
    repo.db.commit()
    repo.db.refresh(destoner)
    return _destoning_state_from(db, tenant, destoner)


def create_destoning_output_bag(
    db: Session, tenant: TenantContext, payload: AcDestoningOutputCreate, user: Any = None
) -> AcDestoningStateOut:
    from app.services.industry.activated_carbon import triplet_capture as ac_triples

    repo = _repo(db, tenant)
    destoner = _resolve_destoner(db, tenant, payload.destoner_resource_code)
    dest_meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
    loaded, outputs = _destoning_lists(dest_meta)
    existing_code = (payload.bag_code or "").strip()
    input_codes = [str(row.get("bag_code")) for row in loaded if row.get("bag_code")]
    lot_code = (payload.lot_code or "").strip() or next(
        (str(row.get("lot_code")) for row in loaded if row.get("lot_code")),
        None,
    )
    now = datetime.now(timezone.utc).isoformat()
    work_order_code = next(
        (str(row.get("work_order_code")) for row in loaded if row.get("work_order_code")),
        None,
    )
    loaded_kg = sum(
        (Decimal(str(row.get("quantity_kg") or 0)) for row in loaded),
        Decimal("0"),
    )
    if not existing_code:
        assert_destoner_output_within_load(
            loaded_kg,
            _deston_output_kg_against_load(loaded, outputs),
            Decimal(str(payload.quantity_kg)),
        )
    if existing_code:
        found = next(
            (row for row in outputs if str(row.get("bag_code") or "") == existing_code),
            None,
        )
        if found is None:
            raise ValidationError(f"Destoning output '{existing_code}' was not found.")
        found["quantity_kg"] = float(payload.quantity_kg)
        if loaded_kg > 0:
            covered = _deston_output_kg_against_load(loaded, outputs)
            if covered > loaded_kg + Decimal("0.001"):
                raise ValidationError(
                    f"Destoner output cannot exceed loaded ({loaded_kg} KG). "
                    f"Remaining: {max(loaded_kg - (covered - Decimal(str(payload.quantity_kg))), Decimal('0'))} KG."
                )
        if lot_code:
            found["lot_code"] = lot_code
        bag_code = existing_code
        destoner.metadata_ = {
            **dest_meta,
            "destoning_loaded_bags": loaded,
            "destoning_output_bags": outputs,
            "destoning_load_events": _destoning_events(dest_meta),
        }
    else:
        bag_code = next_destoning_bag_code(repo.db, tenant.timezone)
        from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

        load_ctc = _destoner_load_ctc(loaded)
        if load_ctc in (None, ""):
            load_ctc = ac_plant_equipment.destoner_plan_meta(
                destoner,
                ac_plant_equipment.tenant_daily_ctc_plan(db, tenant),
                plant_today(tenant.timezone),
            ).get("assigned_ctc")
        kiln_code = next(
            (str(row.get("kiln_resource_code")) for row in loaded if row.get("kiln_resource_code")),
            None,
        )
        outputs.append(
            {
                "bag_code": bag_code,
                "quantity_kg": float(payload.quantity_kg),
                "lot_code": lot_code,
                "created_at": now,
                "input_bag_codes": input_codes,
                "ctc": str(load_ctc) if load_ctc not in (None, "") else None,
                "kiln_resource_code": kiln_code,
                "work_order_code": work_order_code,
                "destoner_resource_code": destoner.resource_code,
                "created_by": _session_actor(user),
            }
        )
        covered = _deston_output_kg_against_load(loaded, outputs)
        events = _destoning_events(dest_meta)
        if covered + Decimal("0.001") >= loaded_kg:
            finished = {str(row.get("bag_code") or "") for row in loaded if row.get("bag_code")}
            events = [row for row in events if str(row.get("bag_code") or "") not in finished]
            next_loaded: list[dict] = []
        else:
            next_loaded = loaded
        destoner.metadata_ = {
            **dest_meta,
            "destoning_loaded_bags": next_loaded,
            "destoning_output_bags": outputs,
            "destoning_load_events": events,
        }
    flag_modified(destoner, "metadata_")
    if not existing_code:
        _stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:ac:destonBag:{bag_code}",
                predicate_uri="urn:nyra:predicate:contained_in",
                object_uri=f"urn:nyra:ac:destoner:{destoner.resource_code}",
                source_table="cfg.resource",
                source_id=destoner.resource_id,
            ),
        )
        _stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:ac:destonBag:{bag_code}",
                predicate_uri="urn:nyra:predicate:usedEquipment",
                object_uri=f"urn:nyra:ac:destoner:{destoner.resource_code}",
                source_table="cfg.resource",
                source_id=destoner.resource_id,
            ),
        )
        for src in input_codes:
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:destonBag:{bag_code}",
                    predicate_uri="urn:nyra:predicate:generatedFrom",
                    object_uri=f"urn:nyra:ac:kilnOutBag:{src}",
                    source_table="cfg.resource",
                    source_id=destoner.resource_id,
                ),
            )
        if work_order_code:
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:destonBag:{bag_code}",
                    predicate_uri="urn:nyra:predicate:assignedTo",
                    object_uri=f"urn:nyra:ac:workOrder:{work_order_code}",
                    source_table="cfg.resource",
                    source_id=destoner.resource_id,
                ),
            )
    param_defs = _kiln_out_qc_param_defs(db, tenant)
    ac_triples.stage_captures_for_values(
        db,
        tenant,
        subject_uri=f"urn:nyra:ac:destonBag:{bag_code}",
        values={
            "destoning_bag_ref": bag_code,
            "deston_output_kg": str(payload.quantity_kg),
            "deston_input_bag_ref": ",".join(input_codes) if not existing_code else None,
        },
        source_table="cfg.resource",
        source_id=destoner.resource_id,
        param_defs=param_defs,
        process_step="DESTONING",
        used_at="execution",
        operation_code="OP-DESTONING",
        flush_only=True,
    )
    if lot_code:
        ac_triples.stage_captures_for_values(
            db,
            tenant,
            subject_uri=f"urn:nyra:ac:lot:{lot_code}",
            values={
                "destoning_bag_ref": bag_code,
                "deston_output_kg": str(payload.quantity_kg),
            },
            source_table="cfg.resource",
            source_id=destoner.resource_id,
            param_defs=param_defs,
            process_step="DESTONING",
            used_at="execution",
            operation_code="OP-DESTONING",
            flush_only=True,
        )
    repo.db.commit()
    repo.db.refresh(destoner)
    return _destoning_state_from(db, tenant, destoner)


def list_destoning_qc_bags(db: Session, tenant: TenantContext) -> list[AcDestoningBagQcOut]:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    plan = ac_plant_equipment.tenant_daily_ctc_plan(db, tenant)
    rows: list[AcDestoningBagQcOut] = []
    ctc_cache: dict[str, str | None] = {}
    for destoner in _list_destoner_resources(db, tenant):
        dest_meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
        _loaded, outputs = _destoning_lists(dest_meta)
        assigned_mesh = ac_plant_equipment.destoner_plan_meta(
            destoner, plan, plant_today(tenant.timezone)
        ).get("assigned_mesh")
        for bag in outputs:
            code = str(bag.get("bag_code") or "")
            if not code:
                continue
            qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
            wo_code = str(bag.get("work_order_code") or "").strip() or None
            rows.append(
                AcDestoningBagQcOut(
                    bag_code=code,
                    quantity_kg=Decimal(str(bag.get("quantity_kg") or 0)),
                    lot_code=bag.get("lot_code"),
                    work_order_code=wo_code,
                    work_order_ctc=ac_work_orders.lookup_work_order_ctc(db, tenant, wo_code, ctc_cache),
                    created_at=bag.get("created_at"),
                    created_by=bag.get("created_by"),
                    user_id=qc.get("user_id"),
                    input_bag_codes=[str(c) for c in (bag.get("input_bag_codes") or []) if c],
                    destoner_resource_code=str(destoner.resource_code or "") or None,
                    assigned_mesh=assigned_mesh,
                    values=qc.get("values") if isinstance(qc.get("values"), dict) else {},
                    saved_at=qc.get("saved_at"),
                )
            )
    rows.sort(key=lambda row: str(row.created_at or ""), reverse=True)
    return rows


def save_destoning_bag_qc(
    db: Session, tenant: TenantContext, payload: AcDestoningBagQcCreate
) -> AcDestoningBagQcOut:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
    from app.services.industry.activated_carbon import process_rules as ac_process_rules
    from app.services.industry.activated_carbon import triplet_capture as ac_triples
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    repo = _repo(db, tenant)
    code = (payload.bag_code or "").strip()
    destoner = None
    dest_meta: dict = {}
    loaded: list[dict] = []
    outputs: list[dict] = []
    found = None
    for machine in _list_destoner_resources(db, tenant):
        meta = machine.metadata_ if isinstance(machine.metadata_, dict) else {}
        loaded_rows, output_rows = _destoning_lists(meta)
        match = next((bag for bag in output_rows if str(bag.get("bag_code") or "") == code), None)
        if match is not None:
            destoner = machine
            dest_meta = meta
            loaded = loaded_rows
            outputs = output_rows
            found = match
            break
    if found is None or destoner is None:
        raise ValidationError(f"Destoning bag '{code}' was not found.")
    existing = found.get("destoning_qc") if isinstance(found.get("destoning_qc"), dict) else None
    if existing and existing.get("saved_at"):
        raise ValidationError(
            f"Destoning quality for bag '{code}' is already saved and cannot be changed."
        )
    values: dict[str, Any] = {}
    for key, raw in (payload.values or {}).items():
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        values[str(key)] = text
    assigned_mesh = ac_plant_equipment.destoner_plan_meta(
        destoner, ac_plant_equipment.tenant_daily_ctc_plan(db, tenant), plant_today(tenant.timezone)
    ).get("assigned_mesh")
    if assigned_mesh:
        values["deston_qc_mesh_config"] = assigned_mesh
    dest = ac_process_rules.destoning_destination_from_stones(
        ac_process_rules.destoning_stones_from_values(values)
    )
    stones_yes = ac_process_rules.destoning_stones_present(
        ac_process_rules.destoning_stones_from_values(values)
    )
    values["deston_qc_stones"] = "yes" if stones_yes else "no"
    values["deston_qc_destination"] = dest
    allowed = ac_process_rules.get_process_rules(db, tenant).get("destoning_destinations") or [
        ac_process_rules.SCREENING_DESTINATION,
        ac_process_rules.DESTONING_REWORK_DESTINATION,
    ]
    if dest not in allowed:
        raise ValidationError(
            "Destoning destination must be Destoning or Screening. "
            "In Stock is set later in post-activation."
        )
    now = datetime.now(timezone.utc).isoformat()
    qc = {
        "values": values,
        "user_id": (payload.user_id or "").strip() or None,
        "saved_at": now,
        "copy_from_bag_code": (payload.copy_from_bag_code or "").strip() or None,
    }
    found["destoning_qc"] = qc
    found["destination"] = dest
    found["deston_qc_destination"] = dest
    destoner.metadata_ = {**dest_meta, "destoning_loaded_bags": loaded, "destoning_output_bags": outputs}
    flag_modified(destoner, "metadata_")
    ac_triples.stage_captures_for_values(
        db,
        tenant,
        subject_uri=f"urn:nyra:ac:destonBag:{code}",
        values=values,
        source_table="cfg.resource",
        source_id=destoner.resource_id,
        param_defs=_kiln_out_qc_param_defs(db, tenant),
        process_step="SCREENING",
        used_at="execution",
        operation_code="OP-DESTON-QC",
    )
    repo.db.commit()
    wo_code = str(found.get("work_order_code") or "").strip() or None
    return AcDestoningBagQcOut(
        bag_code=code,
        quantity_kg=Decimal(str(found.get("quantity_kg") or 0)),
        lot_code=found.get("lot_code"),
        work_order_code=wo_code,
        work_order_ctc=ac_work_orders.lookup_work_order_ctc(db, tenant, wo_code),
        created_at=found.get("created_at"),
        created_by=found.get("created_by"),
        user_id=qc.get("user_id"),
        input_bag_codes=[str(c) for c in (found.get("input_bag_codes") or []) if c],
        destoner_resource_code=str(destoner.resource_code or "") or None,
        assigned_mesh=assigned_mesh,
        values=values,
        saved_at=now,
    )


def _reject_kiln_byproduct_bag(
    db: Session, tenant: TenantContext, bag_code: Optional[str]
) -> None:
    code = (bag_code or "").strip()
    if not code:
        return
    meta = _inward_meta_for_bag(db, tenant, code)
    for row in meta.get("inward_bags") or []:
        if not isinstance(row, dict) or str(row.get("bag_code") or "") != code:
            continue
        if row.get("grade") and not ac_inbound_workflow._is_kiln_feed_bag(row):
            raise ValidationError("Unburnt and Stones stay off the kiln.")
        return


def _inward_meta_for_bag(db: Session, tenant: TenantContext, bag_code: Optional[str]) -> dict:
    code = (bag_code or "").strip()
    if not code:
        return {}
    for order in _repo(db, tenant).query(CustomerOrder).all():
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        for bag in meta.get("inward_bags") or []:
            if isinstance(bag, dict) and str(bag.get("bag_code") or "") == code:
                return meta
    return {}


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
        if lot_status in ("COMPLETED", "STOCKED", "DISPATCHED", "CLOSED", "CANCELLED"):
            raise WorkflowError(
                f"Lot '{lot.lot_code}' is closed and cannot be loaded (status: {lot.status})"
            )
        lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        events = _kiln_feed_event_list(lot_meta)
        loaded_kg = sum(Decimal(str(ev.get("kg") or 0)) for ev in events)
        lot_qty = Decimal(str(lot.lot_quantity or 0))
        kiln_code = (payload.kiln_resource_code or lot_meta.get("kiln_resource_code") or "").strip()
        if not kiln_code:
            raise ValidationError("Select a kiln")
        wo_code = (payload.work_order_code or "").strip()
        if not wo_code:
            raise ValidationError("Select a work order before kiln feed.")
        from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment
        from app.services.industry.activated_carbon import work_orders as ac_work_orders

        work_order = ac_work_orders.get_work_order(db, tenant, wo_code)
        kiln_rows = ac_plant_equipment.ensure_six_kilns(db, tenant)
        kiln_row = next((row for row in kiln_rows if str(row.resource_code or "") == kiln_code), None)
        if kiln_row is None:
            raise ValidationError(f"Kiln '{kiln_code}' was not found.")
        kiln_meta = kiln_row.metadata_ if isinstance(kiln_row.metadata_, dict) else {}

        def _lookup_work_order(code: str):
            try:
                return ac_work_orders.get_work_order(db, tenant, code)
            except ValidationError:
                return None

        output_so_far = ac_work_orders.work_order_output_kg_across_kilns(db, tenant, wo_code)
        if ac_work_orders.work_order_kiln_output_done(
            work_order.get("quantity_kg"), output_so_far, work_order.get("status")
        ):
            raise ValidationError(
                f"Kiln output for work order {wo_code} is complete. Choose another work order."
            )
        ac_work_orders.assert_kiln_accepts_work_order(
            kiln_meta,
            wo_code,
            incoming=work_order,
            lookup=_lookup_work_order,
        )
        assigned = (lot_meta.get("kiln_resource_code") or "").strip()
        if assigned and assigned != kiln_code and not wo_code:
            raise WorkflowError(f"Lot '{lot.lot_code}' is already assigned to {assigned}")

        _reject_kiln_byproduct_bag(db, tenant, payload.bag_code)
        _assert_bag_not_already_in_kiln(db, tenant, payload.bag_code)
        bag = _next_kiln_feed_bag(lot_meta, payload.bag_code)
        if bag is not None:
            bag_code = (bag.get("bag_code") or payload.bag_code or "").strip() or None
            feed_kg = Decimal(
                str(
                    payload.quantity_kg
                    or bag.get("quantity_kg")
                    or bag.get("weight_kg")
                    or 0
                )
            )
        else:
            remaining = lot_qty - loaded_kg
            if remaining <= 0:
                raise WorkflowError(f"Lot '{lot.lot_code}' is already fully loaded into the kiln")
            feed_kg = Decimal(str(payload.quantity_kg or remaining))
            bag_code = (payload.bag_code or lot_meta.get("crusher_bag_code") or "").strip() or None

        _assert_bag_not_already_in_kiln(db, tenant, bag_code)
        if feed_kg <= 0:
            raise ValidationError("Load quantity must be greater than zero")
        if lot_qty > 0 and loaded_kg + feed_kg > lot_qty + Decimal("0.001"):
            raise ValidationError("Load would exceed the lot quantity")
        from app.services.industry.activated_carbon import process_rules as ac_process_rules

        ac_process_rules.assert_drying_before_kiln(
            _inward_meta_for_bag(db, tenant, bag_code),
            ac_process_rules.get_process_rules(db, tenant),
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        first_feed = len(events) == 0
        if payload.lot_quantity is not None and lot_status == "CREATED":
            lot.lot_quantity = payload.lot_quantity
        if lot_status == "CREATED":
            lot.status = payload.status or "IN_PROGRESS"

        claim_kiln_for_lot(
            db, tenant, kiln_code, lot_code=lot.lot_code, share=True
        )
        event = {
            "lot_code": lot.lot_code,
            "bag_code": bag_code,
            "kg": float(feed_kg),
            "loaded_at": now_iso,
            "kiln_resource_code": kiln_code,
            "work_order_code": wo_code,
        }
        events = events + [event]
        loaded_kg = loaded_kg + feed_kg
        lot.metadata_ = {
            **lot_meta,
            "charged_at": lot_meta.get("charged_at") or now_iso,
            "kiln_resource_code": kiln_code,
            "kiln_resource_claimed": True,
            "kiln_live_status": "IN_KILN",
            "kiln_feed_events": events,
            "kiln_loaded_kg": str(loaded_kg),
        }
        flag_modified(lot, "metadata_")
        _append_kiln_resource_feed(db, tenant, kiln_code, event)
        if first_feed:
            _create_process_execution(
                db,
                tenant,
                lot.production_lot_id,
                "ACTIVATION",
                {
                    "kiln_resource_code": kiln_code,
                    "feed_recorded": True,
                    "process_step": "KILN_FEED",
                },
                commit=False,
            )
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:lot:{lot.lot_code}",
                    predicate_uri="urn:nyra:predicate:assignedTo",
                    object_uri=f"urn:nyra:ac:kiln:{kiln_code}",
                    source_table="trn.production_lot",
                    source_id=lot.production_lot_id,
                ),
            )
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:lot:{lot.lot_code}",
                    predicate_uri="urn:nyra:predicate:usedEquipment",
                    object_uri=f"urn:nyra:ac:kiln:{kiln_code}",
                    source_table="trn.production_lot",
                    source_id=lot.production_lot_id,
                ),
            )
        _stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:ac:lot:{lot.lot_code}",
                predicate_uri="urn:nyra:predicate:chargedTo",
                object_uri=(
                    f"urn:nyra:ac:kilnFeed:{lot.lot_code}:{bag_code or now_iso}"
                ),
                source_table="trn.production_lot",
                source_id=lot.production_lot_id,
            ),
        )
        if bag_code:
            _stage_triple(
                db,
                tenant,
                TripleCreate(
                    subject_uri=f"urn:nyra:ac:inwardBag:{bag_code}",
                    predicate_uri="urn:nyra:predicate:chargedTo",
                    object_uri=f"urn:nyra:ac:kiln:{kiln_code}",
                    source_table="trn.production_lot",
                    source_id=lot.production_lot_id,
                ),
            )
        ac_work_orders.record_work_order_load(
            db,
            tenant,
            work_order_code=wo_code,
            quantity_kg=feed_kg,
            kiln_resource_code=kiln_code,
            bag_code=bag_code,
            lot_code=lot.lot_code,
            commit=False,
        )
        _stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:ac:workOrder:{wo_code}",
                predicate_uri="urn:nyra:predicate:assignedTo",
                object_uri=f"urn:nyra:ac:kiln:{kiln_code}",
                source_table="trn.production_lot",
                source_id=lot.production_lot_id,
            ),
        )
        repo.db.commit()
        repo.db.refresh(lot)
        return mes_core_entities._production_lot_out(db, tenant, lot)

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
        now_iso = datetime.now(timezone.utc).isoformat()
        lot_row = repo.get_by_pk(
            ProductionLot, ProductionLot.production_lot_id, lot.production_lot_id
        )
        claim_kiln_for_lot(
            db,
            tenant,
            payload.kiln_resource_code,
            lot_code=lot_row.lot_code,
            share=True,
        )
        feed_kg = Decimal(str(payload.quantity_kg or payload.lot_quantity or lot_row.lot_quantity or 0))
        from app.services.industry.activated_carbon import process_rules as ac_process_rules

        _reject_kiln_byproduct_bag(db, tenant, payload.bag_code)
        ac_process_rules.assert_drying_before_kiln(
            _inward_meta_for_bag(db, tenant, (payload.bag_code or "").strip() or None),
            ac_process_rules.get_process_rules(db, tenant),
        )
        event = {
            "lot_code": lot_row.lot_code,
            "bag_code": (payload.bag_code or "").strip() or None,
            "kg": float(feed_kg),
            "loaded_at": now_iso,
            "kiln_resource_code": payload.kiln_resource_code,
        }
        lot_meta = lot_row.metadata_ if isinstance(lot_row.metadata_, dict) else {}
        lot_row.metadata_ = {
            **lot_meta,
            "charged_at": now_iso,
            "kiln_resource_code": payload.kiln_resource_code,
            "kiln_resource_claimed": True,
            "kiln_live_status": "IN_KILN",
            "kiln_feed_events": [event],
            "kiln_loaded_kg": str(feed_kg),
        }
        flag_modified(lot_row, "metadata_")
        _append_kiln_resource_feed(db, tenant, payload.kiln_resource_code, event)
        _create_process_execution(
            db,
            tenant,
            lot_row.production_lot_id,
            "ACTIVATION",
            {
                "kiln_resource_code": payload.kiln_resource_code,
                "feed_recorded": True,
                "process_step": "KILN_FEED",
            },
        )
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=f"urn:nyra:ac:lot:{lot_row.lot_code}",
                predicate_uri="urn:nyra:predicate:assignedTo",
                object_uri=f"urn:nyra:ac:kiln:{payload.kiln_resource_code}",
                source_table="trn.production_lot",
                source_id=lot_row.production_lot_id,
            ),
        )
        repo.db.commit()
    return mes_core_entities.get_production_lot(db, tenant, lot.production_lot_id)


def create_kiln_parameters(
    db: Session, tenant: TenantContext, payload: AcKilnParametersCreate
) -> AcKilnParameterReadingOut:
    kilns = _list_tenant_kiln_resources(db, tenant)
    kiln_code = (payload.kiln_resource_code or "").strip()
    kiln = next((row for row in kilns if row.resource_code == kiln_code), None)
    if kiln is None and kilns:
        kiln = kilns[0]
    if kiln is None:
        raise ValidationError("No kiln found. Add a kiln in Masters.")
    readings = _kiln_reading_values(payload)
    if not readings:
        raise ValidationError("Enter at least one kiln reading.")
    recorded_at = payload.recorded_at or datetime.now(timezone.utc)
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    entry = {
        "reading_id": str(uuid4()),
        "recorded_at": recorded_at.isoformat(),
        "kiln_resource_code": kiln.resource_code,
        "readings": readings,
    }
    meta = dict(kiln.metadata_ if isinstance(kiln.metadata_, dict) else {})
    history = [row for row in (meta.get(_KILN_READING_META) or []) if isinstance(row, dict)]
    history.insert(0, entry)
    meta[_KILN_READING_META] = history[:200]
    kiln.metadata_ = meta
    flag_modified(kiln, "metadata_")
    db.commit()
    return AcKilnParameterReadingOut(
        reading_id=entry["reading_id"],
        kiln_resource_code=kiln.resource_code,
        recorded_at=recorded_at,
        readings=readings,
    )


def _stage_screening_triples(
    db: Session,
    tenant: TenantContext,
    lot: ProductionLot,
    execution_code: str,
    meta: dict,
) -> None:
    subject = f"urn:nyra:ac:lot:{lot.lot_code}"
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:screenedAt",
            object_uri=f"urn:nyra:ac:screening:{execution_code}",
            source_table="exec.operation_execution",
            source_id=None,
        ),
    )
    for field, param_uri in (
        ("mesh_size", "urn:nyra:ac:parameter:SCREEN_MESH_SIZE"),
        ("good_kg", "urn:nyra:ac:parameter:GOOD_KG"),
        ("overs_kg", "urn:nyra:ac:parameter:OVERS_KG"),
        ("fines_kg", "urn:nyra:ac:parameter:FINES_KG"),
    ):
        value = meta.get(field)
        if value is None:
            continue
        datatype = (
            "http://www.w3.org/2001/XMLSchema#string"
            if field == "mesh_size"
            else "http://www.w3.org/2001/XMLSchema#decimal"
        )
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=param_uri,
                object_literal=str(value),
                object_datatype=datatype,
                source_table="exec.operation_execution",
                source_id=None,
            ),
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
    _stage_screening_triples(db, tenant, lot, result.execution_code, meta)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    lot.metadata_ = {
        **lot_meta,
        "screening_recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    repo.db.flush()
    ac_stock.try_stock_lot_after_pipeline(db, tenant, payload.production_lot_id)
    return result


def _stage_grade_separation_triples(
    db: Session,
    tenant: TenantContext,
    lot: ProductionLot,
    execution_code: str,
    meta: dict,
) -> None:
    subject = f"urn:nyra:ac:lot:{lot.lot_code}"
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:captures",
            object_uri=f"urn:nyra:ac:gradeSeparation:{execution_code}",
            source_table="exec.operation_execution",
            source_id=None,
        ),
    )
    for field, param_uri in (
        ("grade_code", "urn:nyra:ac:parameter:GRADE_CODE"),
        ("separated_kg", "urn:nyra:ac:parameter:SEPARATED_KG"),
        ("grade_yield_pct", "urn:nyra:ac:parameter:GRADE_YIELD_PCT"),
        ("overs_grade_kg", "urn:nyra:ac:parameter:OVERS_GRADE_KG"),
        ("fines_grade_kg", "urn:nyra:ac:parameter:FINES_GRADE_KG"),
    ):
        value = meta.get(field)
        if value is None:
            continue
        datatype = (
            "http://www.w3.org/2001/XMLSchema#string"
            if field == "grade_code"
            else "http://www.w3.org/2001/XMLSchema#decimal"
        )
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=param_uri,
                object_literal=str(value),
                object_datatype=datatype,
                source_table="exec.operation_execution",
                source_id=None,
            ),
        )


def create_grade_separation_record(
    db: Session, tenant: TenantContext, payload: AcGradeSeparationCreate
) -> OperationExecutionOut:
    meta = {
        k: v
        for k, v in {
            "grade_code": payload.grade_code,
            "separated_kg": payload.separated_kg,
            "grade_yield_pct": payload.grade_yield_pct,
            "overs_grade_kg": payload.overs_grade_kg,
            "fines_grade_kg": payload.fines_grade_kg,
        }.items()
        if v is not None
    }
    result = _create_process_execution(
        db, tenant, payload.production_lot_id, "GRADE_SEPARATION", meta
    )
    repo = _repo(db, tenant)
    lot = repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
    )
    _stage_grade_separation_triples(db, tenant, lot, result.execution_code, meta)
    lot_meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
    lot.metadata_ = {
        **lot_meta,
        "grade_code": payload.grade_code,
        "grade_separation_at": datetime.now(timezone.utc).isoformat(),
    }
    repo.db.flush()
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

    def _qc_meta_val(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    qc_meta = {
        k: _qc_meta_val(v)
        for k, v in {
            "iodine_mg_g": payload.iodine_mg_g,
            "ash_pct": payload.ash_pct,
            "moisture_pct": payload.moisture_pct,
            "bulk_density": payload.bulk_density,
            "remarks": payload.remarks,
        }.items()
        if v is not None
    }
    check_row.metadata_ = {
        **(check_row.metadata_ if isinstance(check_row.metadata_, dict) else {}),
        **qc_meta,
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


get_post_activation_state = ac_post_activation.get_post_activation_state
load_post_activation_bag = ac_post_activation.load_post_activation_bag
unload_post_activation_bag = ac_post_activation.unload_post_activation_bag
create_post_activation_output_bag = ac_post_activation.create_post_activation_output_bag
list_post_activation_quality = ac_post_activation.list_post_activation_quality
save_post_activation_quality = ac_post_activation.save_post_activation_quality
