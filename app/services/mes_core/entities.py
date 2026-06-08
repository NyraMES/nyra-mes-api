"""nyra_mes_core domain services — generic, industry-agnostic, tenant-scoped."""

from __future__ import annotations

from decimal import Decimal
from typing import List
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
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
    CustomerCreate,
    CustomerOrderCreate,
    CustomerOrderCreateResponse,
    CustomerOrderLineCreate,
    CustomerOrderLineOut,
    CustomerOrderOut,
    CustomerOut,
    EquipmentCreate,
    EquipmentOut,
    FeasibilityCheckCreate,
    FeasibilityCheckOut,
    InwardOrderCreate,
    OperationExecutionCreate,
    OperationExecutionOut,
    ProductCreate,
    ProductOut,
    ProductionLotCreate,
    ProductionLotOut,
    ProductionLotSplitRequest,
    ProductionLotSplitResponse,
    ProductionOrderCreate,
    ProductionOrderOut,
    QualityCheckCreate,
    QualityCheckOut,
    ResourceCreate,
    ResourceOut,
    RoutingCreate,
    RoutingOperationCreate,
    RoutingOperationOut,
    RoutingOut,
    RoutingWithOperationsCreate,
    RoutingWithOperationsOut,
    SupplierCreate,
    SupplierOut,
    TripleCreate,
    TripleOut,
)
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.ids import resolve_business_code


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


# --- Customers ---


def list_customers(db: Session, tenant: TenantContext) -> List[CustomerOut]:
    rows = (
        _repo(db, tenant).query(Customer).order_by(Customer.customer_name).all()
    )
    return [CustomerOut.model_validate(r) for r in rows]


def get_customer(db: Session, tenant: TenantContext, customer_id: UUID) -> CustomerOut:
    row = _repo(db, tenant).get_by_pk(Customer, Customer.customer_id, customer_id)
    return CustomerOut.model_validate(row)


def create_customer(
    db: Session, tenant: TenantContext, payload: CustomerCreate
) -> CustomerOut:
    repo = _repo(db, tenant)
    code = resolve_business_code(
        db,
        provided=payload.customer_code,
        entity="customer",
    )
    row = repo.add(
        Customer(
            customer_code=code,
            customer_name=payload.customer_name,
            status=payload.status,
        )
    )
    return CustomerOut.model_validate(repo.commit_refresh(row))


# --- Suppliers ---


def list_suppliers(db: Session, tenant: TenantContext) -> List[SupplierOut]:
    rows = (
        _repo(db, tenant).query(Supplier).order_by(Supplier.supplier_name).all()
    )
    return [SupplierOut.model_validate(r) for r in rows]


def get_supplier(db: Session, tenant: TenantContext, supplier_id: UUID) -> SupplierOut:
    row = _repo(db, tenant).get_by_pk(Supplier, Supplier.supplier_id, supplier_id)
    return SupplierOut.model_validate(row)


def create_supplier(
    db: Session, tenant: TenantContext, payload: SupplierCreate
) -> SupplierOut:
    repo = _repo(db, tenant)
    code = resolve_business_code(
        db,
        provided=payload.supplier_code,
        entity="supplier",
    )
    row = repo.add(
        Supplier(
            supplier_code=code,
            supplier_name=payload.supplier_name,
            status=payload.status,
        )
    )
    return SupplierOut.model_validate(repo.commit_refresh(row))


# --- Products ---


def list_products(db: Session, tenant: TenantContext) -> List[ProductOut]:
    rows = _repo(db, tenant).query(Product).order_by(Product.product_code).all()
    return [ProductOut.model_validate(r) for r in rows]


def get_product(db: Session, tenant: TenantContext, product_id: UUID) -> ProductOut:
    row = _repo(db, tenant).get_by_pk(Product, Product.product_id, product_id)
    return ProductOut.model_validate(row)


def create_product(
    db: Session, tenant: TenantContext, payload: ProductCreate
) -> ProductOut:
    repo = _repo(db, tenant)
    code = resolve_business_code(
        db,
        provided=payload.product_code,
        entity="product",
    )
    row = repo.add(
        Product(
            product_code=code,
            product_name=payload.product_name,
            product_type=payload.product_type,
            uom=payload.uom,
            status=payload.status,
        )
    )
    return ProductOut.model_validate(repo.commit_refresh(row))


# --- Resources ---


def list_resources(db: Session, tenant: TenantContext) -> List[ResourceOut]:
    rows = _repo(db, tenant).query(Resource).order_by(Resource.resource_code).all()
    return [ResourceOut.model_validate(r) for r in rows]


def get_resource(db: Session, tenant: TenantContext, resource_id: UUID) -> ResourceOut:
    row = _repo(db, tenant).get_by_pk(Resource, Resource.resource_id, resource_id)
    return ResourceOut.model_validate(row)


def create_resource(
    db: Session, tenant: TenantContext, payload: ResourceCreate
) -> ResourceOut:
    repo = _repo(db, tenant)
    code = resolve_business_code(
        db,
        provided=payload.resource_code,
        entity="resource",
    )
    row = repo.add(
        Resource(
            resource_code=code,
            resource_name=payload.resource_name,
            resource_type=payload.resource_type,
            status=payload.status,
        )
    )
    return ResourceOut.model_validate(repo.commit_refresh(row))


# --- Equipment ---


def list_equipment(db: Session, tenant: TenantContext) -> List[EquipmentOut]:
    rows = _repo(db, tenant).query(Equipment).order_by(Equipment.equipment_code).all()
    return [EquipmentOut.model_validate(r) for r in rows]


def get_equipment(
    db: Session, tenant: TenantContext, equipment_id: UUID
) -> EquipmentOut:
    row = _repo(db, tenant).get_by_pk(Equipment, Equipment.equipment_id, equipment_id)
    return EquipmentOut.model_validate(row)


def create_equipment(
    db: Session, tenant: TenantContext, payload: EquipmentCreate
) -> EquipmentOut:
    repo = _repo(db, tenant)
    code = resolve_business_code(
        db,
        provided=payload.equipment_code,
        entity="equipment",
    )
    row = repo.add(
        Equipment(
            equipment_code=code,
            equipment_name=payload.equipment_name,
            resource_id=payload.resource_id,
            equipment_type=payload.equipment_type,
            status=payload.status,
        )
    )
    return EquipmentOut.model_validate(repo.commit_refresh(row))


# --- Routings ---


def _routing_operation_out(row: RoutingOperation) -> RoutingOperationOut:
    meta = row.metadata_ or {}
    return RoutingOperationOut(
        routing_operation_id=row.routing_operation_id,
        tenant_id=row.tenant_id,
        routing_id=row.routing_id,
        operation_code=row.operation_code,
        operation_sequence=row.operation_sequence,
        operation_name=row.operation_name,
        standard_cycle_min=row.standard_cycle_min,
        process_id=meta.get("process_id"),
        inspection_required=meta.get("inspection_required"),
    )


def _routing_out(db: Session, tenant: TenantContext, routing: Routing) -> RoutingOut:
    repo = _repo(db, tenant)
    ops = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    return RoutingOut(
        routing_id=routing.routing_id,
        tenant_id=routing.tenant_id,
        routing_code=routing.routing_code,
        product_id=routing.product_id,
        routing_version=routing.routing_version,
        process_family=routing.process_family,
        is_active=routing.is_active,
        operations=[_routing_operation_out(o) for o in ops],
        created_at=routing.created_at,
    )


def list_routings(db: Session, tenant: TenantContext) -> List[RoutingOut]:
    rows = _repo(db, tenant).query(Routing).order_by(Routing.routing_code).all()
    return [_routing_out(db, tenant, r) for r in rows]


def get_routing(db: Session, tenant: TenantContext, routing_id: UUID) -> RoutingOut:
    row = _repo(db, tenant).get_by_pk(Routing, Routing.routing_id, routing_id)
    return _routing_out(db, tenant, row)


def create_routing(
    db: Session, tenant: TenantContext, payload: RoutingCreate
) -> RoutingOut:
    repo = _repo(db, tenant)
    repo.get_by_pk(Product, Product.product_id, payload.product_id)
    code = resolve_business_code(
        db,
        provided=payload.routing_code,
        entity="routing",
    )
    row = repo.add(
        Routing(
            routing_code=code,
            product_id=payload.product_id,
            routing_version=payload.routing_version,
            process_family=payload.process_family,
            is_active=payload.is_active,
        )
    )
    return _routing_out(db, tenant, repo.commit_refresh(row))


def create_routing_with_operations(
    db: Session, tenant: TenantContext, payload: RoutingWithOperationsCreate
) -> RoutingWithOperationsOut:
    """Atomically create a routing and all operations (Routing Master save)."""
    repo = _repo(db, tenant)
    repo.get_by_pk(Product, Product.product_id, payload.product_id)

    routing_code = resolve_business_code(
        db,
        provided=payload.routing_code,
        entity="routing",
    )
    routing = repo.add(
        Routing(
            routing_code=routing_code,
            product_id=payload.product_id,
            routing_version=payload.routing_version,
            process_family=payload.process_family,
            is_active=payload.is_active,
        )
    )
    repo.db.flush()

    seen_sequences: set[int] = set()
    op_rows: list[RoutingOperation] = []
    for op_in in payload.operations:
        if op_in.operation_sequence in seen_sequences:
            raise ValidationError(
                f"Duplicate operation_sequence {op_in.operation_sequence} in request"
            )
        seen_sequences.add(op_in.operation_sequence)

        op_code = resolve_business_code(
            db,
            provided=op_in.operation_code,
            entity="routing_operation",
        )
        metadata: dict = {
            "inspection_required": op_in.inspection_required,
        }
        if op_in.process_id:
            metadata["process_id"] = str(op_in.process_id)
        if op_in.process_code:
            metadata["process_code"] = op_in.process_code
        if op_in.process_name:
            metadata["process_name"] = op_in.process_name
        if op_in.process_type:
            metadata["process_type"] = op_in.process_type

        row = repo.add(
            RoutingOperation(
                routing_id=routing.routing_id,
                operation_code=op_code,
                operation_sequence=op_in.operation_sequence,
                operation_name=op_in.operation_name,
                standard_cycle_min=op_in.standard_cycle_time_minutes,
                metadata_=metadata,
            )
        )
        op_rows.append(row)

    try:
        repo.db.commit()
    except IntegrityError as exc:
        repo.db.rollback()
        message = str(getattr(exc, "orig", exc))
        if "uq_routing_operation_code" in message or "operation_code" in message:
            raise ValidationError(
                "An operation with the same code already exists on this routing. "
                "Use unique operation codes per routing step."
            ) from exc
        if "uq_routing_operation_seq" in message or "operation_sequence" in message:
            raise ValidationError(
                "Duplicate operation sequence on this routing."
            ) from exc
        raise ValidationError("Could not save routing — a database constraint was violated.") from exc

    for row in op_rows:
        repo.db.refresh(row)
    repo.db.refresh(routing)

    return RoutingWithOperationsOut(
        routing=_routing_out(db, tenant, routing),
        operations=[_routing_operation_out(row) for row in op_rows],
    )


# --- Customer orders ---


def _delivery_date_from_metadata(metadata: dict | None):
    raw = (metadata or {}).get("delivery_date")
    if not raw:
        return None
    if hasattr(raw, "isoformat"):
        return raw
    from datetime import date

    return date.fromisoformat(str(raw)[:10])


def _customer_order_line_out(
    db: Session, tenant: TenantContext, row: CustomerOrderLine
) -> CustomerOrderLineOut:
    product = (
        _repo(db, tenant)
        .query(Product)
        .filter(Product.product_id == row.product_id)
        .first()
    )
    return CustomerOrderLineOut(
        order_line_id=row.order_line_id,
        tenant_id=row.tenant_id,
        order_id=row.order_id,
        line_code=row.line_code,
        product_id=row.product_id,
        product_code=product.product_code if product else None,
        quantity=row.quantity,
        uom=row.uom,
        status=row.status,
        created_at=row.created_at,
    )


def _customer_order_out(
    db: Session, tenant: TenantContext, row: CustomerOrder
) -> CustomerOrderOut:
    customer = None
    if row.customer_id is not None:
        customer = (
            _repo(db, tenant)
            .query(Customer)
            .filter(Customer.customer_id == row.customer_id)
            .first()
        )
    supplier = None
    if getattr(row, "supplier_id", None) is not None:
        supplier = (
            _repo(db, tenant)
            .query(Supplier)
            .filter(Supplier.supplier_id == row.supplier_id)
            .first()
        )
    lines = (
        _repo(db, tenant)
        .query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == row.customer_order_id)
        .order_by(CustomerOrderLine.line_code)
        .all()
    )
    return CustomerOrderOut(
        customer_order_id=row.customer_order_id,
        tenant_id=row.tenant_id,
        order_code=row.order_code,
        customer_id=row.customer_id,
        customer_code=customer.customer_code if customer else None,
        customer_name=customer.customer_name if customer else None,
        supplier_id=getattr(row, "supplier_id", None),
        supplier_code=supplier.supplier_code if supplier else None,
        supplier_name=supplier.supplier_name if supplier else None,
        order_date=row.order_date,
        delivery_date=_delivery_date_from_metadata(row.metadata_),
        status=row.status,
        lines=[_customer_order_line_out(db, tenant, line) for line in lines],
        created_at=row.created_at,
    )


def list_customer_orders(
    db: Session, tenant: TenantContext
) -> List[CustomerOrderOut]:
    rows = (
        _repo(db, tenant)
        .query(CustomerOrder)
        .order_by(CustomerOrder.order_code)
        .all()
    )
    return [_customer_order_out(db, tenant, row) for row in rows]


def create_customer_order(
    db: Session, tenant: TenantContext, payload: CustomerOrderCreate
) -> CustomerOrderCreateResponse:
    repo = _repo(db, tenant)
    if payload.customer_id is None and payload.supplier_id is None:
        raise ValidationError("customer_id or supplier_id is required")
    if payload.customer_id is not None:
        repo.get_by_pk(Customer, Customer.customer_id, payload.customer_id)
    if payload.supplier_id is not None:
        repo.get_by_pk(Supplier, Supplier.supplier_id, payload.supplier_id)
    repo.get_by_pk(Product, Product.product_id, payload.line.product_id)

    order_code = resolve_business_code(
        db,
        provided=payload.order_code,
        entity="customer_order",
    )
    line_code = resolve_business_code(
        db,
        provided=payload.line.line_code,
        entity="customer_order_line",
    )

    metadata: dict = {}
    if payload.delivery_date:
        metadata["delivery_date"] = payload.delivery_date.isoformat()

    order = repo.add(
        CustomerOrder(
            order_code=order_code,
            customer_id=payload.customer_id,
            supplier_id=payload.supplier_id,
            status=payload.status,
            metadata_=metadata,
        )
    )
    repo.db.flush()

    line = repo.add(
        CustomerOrderLine(
            order_id=order.customer_order_id,
            line_code=line_code,
            product_id=payload.line.product_id,
            quantity=payload.line.quantity,
            uom=payload.line.uom,
            status=payload.line.status,
        )
    )
    repo.commit_refresh(line)
    repo.db.refresh(order)
    return CustomerOrderCreateResponse(
        order=_customer_order_out(db, tenant, order),
        line=_customer_order_line_out(db, tenant, line),
    )


def create_inward_order(
    db: Session, tenant: TenantContext, payload: InwardOrderCreate
) -> CustomerOrderCreateResponse:
    """Raw material inward receipt — supplier only (no end customer)."""
    return create_customer_order(
        db,
        tenant,
        CustomerOrderCreate(
            order_code=payload.order_code,
            supplier_id=payload.supplier_id,
            status=payload.status,
            line=payload.line,
        ),
    )


def create_make_to_stock_order(
    db: Session,
    tenant: TenantContext,
    *,
    order_code: str | None,
    line: CustomerOrderLineCreate,
    source_inward_order_id: UUID | None = None,
) -> CustomerOrderCreateResponse:
    """Internal manufacturing batch — no customer or supplier on the order."""
    repo = _repo(db, tenant)
    repo.get_by_pk(Product, Product.product_id, line.product_id)

    resolved_order_code = resolve_business_code(
        db,
        provided=order_code,
        entity="customer_order",
    )
    line_code = resolve_business_code(
        db,
        provided=line.line_code,
        entity="customer_order_line",
    )
    metadata: dict = {"flow": "MAKE_TO_STOCK"}
    if source_inward_order_id is not None:
        metadata["source_inward_order_id"] = str(source_inward_order_id)

    order = repo.add(
        CustomerOrder(
            order_code=resolved_order_code,
            customer_id=None,
            supplier_id=None,
            status="OPEN",
            metadata_=metadata,
        )
    )
    repo.db.flush()

    line_row = repo.add(
        CustomerOrderLine(
            order_id=order.customer_order_id,
            line_code=line_code,
            product_id=line.product_id,
            quantity=line.quantity,
            uom=line.uom,
            status=line.status,
        )
    )
    repo.commit_refresh(line_row)
    repo.db.refresh(order)
    return CustomerOrderCreateResponse(
        order=_customer_order_out(db, tenant, order),
        line=_customer_order_line_out(db, tenant, line_row),
    )


def create_customer_order_line(
    db: Session,
    tenant: TenantContext,
    customer_order_id: UUID,
    payload: CustomerOrderLineCreate,
) -> CustomerOrderLineOut:
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, customer_order_id
    )
    repo.get_by_pk(Product, Product.product_id, payload.product_id)
    line_code = resolve_business_code(
        db,
        provided=payload.line_code,
        entity="customer_order_line",
    )
    line = repo.add(
        CustomerOrderLine(
            order_id=order.customer_order_id,
            line_code=line_code,
            product_id=payload.product_id,
            quantity=payload.quantity,
            uom=payload.uom,
            status=payload.status,
        )
    )
    return _customer_order_line_out(db, tenant, repo.commit_refresh(line))


# --- Production orders ---


def _production_order_out(
    db: Session, tenant: TenantContext, row: ProductionOrder
) -> ProductionOrderOut:
    line = (
        _repo(db, tenant)
        .query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_line_id == row.order_line_id)
        .first()
    )
    product_code = None
    if line:
        product = (
            _repo(db, tenant)
            .query(Product)
            .filter(Product.product_id == line.product_id)
            .first()
        )
        product_code = product.product_code if product else None
    return ProductionOrderOut(
        production_order_id=row.production_order_id,
        tenant_id=row.tenant_id,
        production_order_code=row.production_order_code,
        order_line_id=row.order_line_id,
        order_line_code=line.line_code if line else None,
        product_code=product_code,
        planned_quantity=row.planned_quantity,
        status=row.status,
        created_at=row.created_at,
    )


def list_production_orders(
    db: Session, tenant: TenantContext
) -> List[ProductionOrderOut]:
    rows = (
        _repo(db, tenant)
        .query(ProductionOrder)
        .order_by(ProductionOrder.production_order_code)
        .all()
    )
    return [_production_order_out(db, tenant, row) for row in rows]


def get_production_order(
    db: Session, tenant: TenantContext, production_order_id: UUID
) -> ProductionOrderOut:
    row = _repo(db, tenant).get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, production_order_id
    )
    return _production_order_out(db, tenant, row)


def create_production_order(
    db: Session, tenant: TenantContext, payload: ProductionOrderCreate
) -> ProductionOrderOut:
    repo = _repo(db, tenant)
    line = repo.get_by_pk(
        CustomerOrderLine, CustomerOrderLine.order_line_id, payload.order_line_id
    )
    line_qty = Decimal(str(line.quantity))
    planned = Decimal(str(payload.planned_quantity))
    if line_qty != planned:
        raise ValidationError(
            "Production order planned quantity must equal order line quantity",
            details={"order_line_quantity": str(line_qty), "planned_quantity": str(planned)},
        )
    existing = (
        repo.query(ProductionOrder)
        .filter(ProductionOrder.order_line_id == payload.order_line_id)
        .first()
    )
    if existing:
        raise ValidationError(
            "This order line already has a production order",
            details={"production_order_code": existing.production_order_code},
        )
    code = resolve_business_code(
        db,
        provided=payload.production_order_code,
        entity="production_order",
    )
    row = repo.add(
        ProductionOrder(
            production_order_code=code,
            order_line_id=payload.order_line_id,
            planned_quantity=payload.planned_quantity,
            status=payload.status,
        )
    )
    return _production_order_out(db, tenant, repo.commit_refresh(row))


def get_production_order_by_code(
    db: Session, tenant: TenantContext, production_order_code: str
) -> ProductionOrderOut:
    row = _repo(db, tenant).get_by_code(
        ProductionOrder, ProductionOrder.production_order_code, production_order_code
    )
    return _production_order_out(db, tenant, row)


# --- Production lots ---


def _production_lot_out(
    db: Session, tenant: TenantContext, row: ProductionLot
) -> ProductionLotOut:
    po = (
        _repo(db, tenant)
        .query(ProductionOrder)
        .filter(ProductionOrder.production_order_id == row.production_order_id)
        .first()
    )
    return ProductionLotOut(
        production_lot_id=row.production_lot_id,
        tenant_id=row.tenant_id,
        lot_code=row.lot_code,
        production_order_id=row.production_order_id,
        production_order_code=po.production_order_code if po else None,
        lot_quantity=row.lot_quantity,
        status=row.status,
        created_at=row.created_at,
    )


def list_production_lots(
    db: Session, tenant: TenantContext
) -> List[ProductionLotOut]:
    rows = (
        _repo(db, tenant)
        .query(ProductionLot)
        .order_by(ProductionLot.lot_code)
        .all()
    )
    return [_production_lot_out(db, tenant, row) for row in rows]


def get_production_lot(
    db: Session, tenant: TenantContext, production_lot_id: UUID
) -> ProductionLotOut:
    row = _repo(db, tenant).get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, production_lot_id
    )
    return _production_lot_out(db, tenant, row)


def create_production_lot(
    db: Session, tenant: TenantContext, payload: ProductionLotCreate
) -> ProductionLotOut:
    repo = _repo(db, tenant)
    po = repo.get_by_pk(
        ProductionOrder,
        ProductionOrder.production_order_id,
        payload.production_order_id,
    )
    planned = Decimal(str(po.planned_quantity or 0))
    new_qty = Decimal(str(payload.lot_quantity))
    existing_total = sum(
        Decimal(str(row.lot_quantity or 0))
        for row in repo.query(ProductionLot)
        .filter(ProductionLot.production_order_id == po.production_order_id)
        .all()
    )
    if existing_total + new_qty > planned:
        remaining = planned - existing_total
        raise ValidationError(
            f"Lot quantity exceeds production order {po.production_order_code} capacity. "
            f"Planned: {planned} KG; already charged across existing lot(s): {existing_total} KG; "
            f"requested: {new_qty} KG; remaining capacity: {max(remaining, Decimal('0'))} KG.",
            details={
                "production_order_code": po.production_order_code,
                "planned_quantity": str(planned),
                "existing_lot_quantity": str(existing_total),
                "requested_lot_quantity": str(new_qty),
                "remaining_capacity": str(max(remaining, Decimal("0"))),
            },
        )
    code = resolve_business_code(
        db,
        provided=payload.lot_code,
        entity="production_lot",
    )
    row = repo.add(
        ProductionLot(
            lot_code=code,
            production_order_id=payload.production_order_id,
            lot_quantity=payload.lot_quantity,
            status=payload.status,
        )
    )
    return _production_lot_out(db, tenant, repo.commit_refresh(row))


def split_production_lots(
    db: Session,
    tenant: TenantContext,
    production_order_id: UUID,
    payload: ProductionLotSplitRequest,
) -> ProductionLotSplitResponse:
    repo = _repo(db, tenant)
    po = repo.get_by_pk(
        ProductionOrder, ProductionOrder.production_order_id, production_order_id
    )
    planned = Decimal(str(po.planned_quantity or 0))
    split_total = sum(Decimal(str(item.lot_quantity)) for item in payload.lots)
    if split_total != planned:
        raise ValidationError(
            "Lot split must allocate the full planned production quantity",
            details={"planned_quantity": str(planned), "split_total": str(split_total)},
        )

    existing = (
        repo.query(ProductionLot)
        .filter(ProductionLot.production_order_id == po.production_order_id)
        .count()
    )
    if existing:
        raise ValidationError(
            "This production order is already split into lots. Lot split cannot be performed again."
        )

    created: list[ProductionLot] = []
    for item in payload.lots:
        code = resolve_business_code(
            db,
            provided=None,
            entity="production_lot",
        )
        lot = repo.add(
            ProductionLot(
                lot_code=code,
                production_order_id=po.production_order_id,
                lot_quantity=item.lot_quantity,
                status=item.status,
            )
        )
        created.append(lot)
    repo.db.commit()
    for lot in created:
        repo.db.refresh(lot)
    repo.db.refresh(po)
    return ProductionLotSplitResponse(
        production_order=_production_order_out(db, tenant, po),
        lots=[_production_lot_out(db, tenant, lot) for lot in created],
    )


# --- Feasibility checks ---


def list_feasibility_checks(
    db: Session, tenant: TenantContext
) -> List[FeasibilityCheckOut]:
    rows = (
        _repo(db, tenant)
        .query(FeasibilityCheck)
        .order_by(FeasibilityCheck.check_code)
        .all()
    )
    return [FeasibilityCheckOut.model_validate(r) for r in rows]


def get_feasibility_check(
    db: Session, tenant: TenantContext, feasibility_check_id: UUID
) -> FeasibilityCheckOut:
    row = _repo(db, tenant).get_by_pk(
        FeasibilityCheck, FeasibilityCheck.feasibility_check_id, feasibility_check_id
    )
    return FeasibilityCheckOut.model_validate(row)


def create_feasibility_check(
    db: Session, tenant: TenantContext, payload: FeasibilityCheckCreate
) -> FeasibilityCheckOut:
    repo = _repo(db, tenant)
    repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
    )
    code = resolve_business_code(
        db,
        provided=payload.check_code,
        entity="feasibility_check",
    )
    row = repo.add(
        FeasibilityCheck(
            check_code=code,
            production_lot_id=payload.production_lot_id,
            overall_status=payload.overall_status,
        )
    )
    return FeasibilityCheckOut.model_validate(repo.commit_refresh(row))


# --- Execution ---


def list_executions(
    db: Session, tenant: TenantContext
) -> List[OperationExecutionOut]:
    rows = (
        _repo(db, tenant)
        .query(OperationExecution)
        .order_by(OperationExecution.execution_code)
        .all()
    )
    return [OperationExecutionOut.model_validate(r) for r in rows]


def get_execution(
    db: Session, tenant: TenantContext, execution_id: UUID
) -> OperationExecutionOut:
    row = _repo(db, tenant).get_by_pk(
        OperationExecution, OperationExecution.execution_id, execution_id
    )
    return OperationExecutionOut.model_validate(row)


def create_execution(
    db: Session, tenant: TenantContext, payload: OperationExecutionCreate
) -> OperationExecutionOut:
    repo = _repo(db, tenant)
    repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
    )
    repo.get_by_pk(
        RoutingOperation,
        RoutingOperation.routing_operation_id,
        payload.routing_operation_id,
    )
    code = resolve_business_code(
        db,
        provided=payload.execution_code,
        entity="operation_execution",
    )
    row = repo.add(
        OperationExecution(
            execution_code=code,
            production_lot_id=payload.production_lot_id,
            routing_operation_id=payload.routing_operation_id,
            equipment_id=payload.equipment_id,
            status=payload.status,
        )
    )
    return OperationExecutionOut.model_validate(repo.commit_refresh(row))


# --- Quality checks ---


def list_quality_checks(
    db: Session, tenant: TenantContext
) -> List[QualityCheckOut]:
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .order_by(QualityCheck.check_code)
        .all()
    )
    return [QualityCheckOut.model_validate(r) for r in rows]


def get_quality_check(
    db: Session, tenant: TenantContext, quality_check_id: UUID
) -> QualityCheckOut:
    row = _repo(db, tenant).get_by_pk(
        QualityCheck, QualityCheck.quality_check_id, quality_check_id
    )
    return QualityCheckOut.model_validate(row)


def create_quality_check(
    db: Session, tenant: TenantContext, payload: QualityCheckCreate
) -> QualityCheckOut:
    repo = _repo(db, tenant)
    repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, payload.production_lot_id
    )
    code = resolve_business_code(
        db,
        provided=payload.check_code,
        entity="quality_check",
    )
    row = repo.add(
        QualityCheck(
            check_code=code,
            production_lot_id=payload.production_lot_id,
            check_type=payload.check_type,
            status=payload.status,
        )
    )
    return QualityCheckOut.model_validate(repo.commit_refresh(row))


# --- KG triples ---


def list_triples(db: Session, tenant: TenantContext) -> List[TripleOut]:
    rows = (
        _repo(db, tenant)
        .query(TripleStoreStaging)
        .order_by(TripleStoreStaging.created_at.desc())
        .all()
    )
    return [TripleOut.model_validate(r) for r in rows]


def get_triple(db: Session, tenant: TenantContext, triple_id: UUID) -> TripleOut:
    row = _repo(db, tenant).get_by_pk(
        TripleStoreStaging, TripleStoreStaging.triple_id, triple_id
    )
    return TripleOut.model_validate(row)


def create_triple(
    db: Session, tenant: TenantContext, payload: TripleCreate
) -> TripleOut:
    repo = _repo(db, tenant)
    row = repo.add(
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
    return TripleOut.model_validate(repo.commit_refresh(row))
