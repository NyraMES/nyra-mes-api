"""Transactional models in nyra_mes_core (trn.* schema) — all tenant-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.mes_core_base import MesCoreBase
from app.models.mes_core.scoping import workspace_id_column


class ProductionOrder(MesCoreBase):
    __tablename__ = "production_order"
    __table_args__ = {"schema": "trn"}

    production_order_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    production_order_code = Column(String(64), nullable=False)
    order_line_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.customer_order_line.order_line_id"),
        nullable=False,
    )
    planned_quantity = Column(Numeric(18, 4), nullable=False)
    status = Column(String(32), nullable=False, default="PLANNED")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class ProductionLot(MesCoreBase):
    __tablename__ = "production_lot"
    __table_args__ = {"schema": "trn"}

    production_lot_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    lot_code = Column(String(64), nullable=False)
    production_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.production_order.production_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    lot_quantity = Column(Numeric(18, 4), nullable=False)
    status = Column(String(32), nullable=False, default="CREATED")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class FeasibilityCheck(MesCoreBase):
    __tablename__ = "feasibility_check"
    __table_args__ = {"schema": "trn"}

    feasibility_check_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    check_code = Column(String(64), nullable=False)
    production_lot_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.production_lot.production_lot_id"),
        nullable=False,
    )
    overall_status = Column(String(32), nullable=False, default="PENDING")
    checked_at = Column(DateTime(timezone=True))
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class CustomerOrder(MesCoreBase):
    """Included for FK integrity when creating production orders."""

    __tablename__ = "customer_order"
    __table_args__ = {"schema": "trn"}

    customer_order_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    order_code = Column(String(64), nullable=False)
    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("mst.customer.customer_id"), nullable=True
    )
    supplier_id = Column(
        UUID(as_uuid=True), ForeignKey("mst.supplier.supplier_id"), nullable=True
    )
    order_date = Column(Date, nullable=False, server_default=func.current_date())
    status = Column(String(32), nullable=False, default="OPEN")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class CustomerOrderLine(MesCoreBase):
    __tablename__ = "customer_order_line"
    __table_args__ = {"schema": "trn"}

    order_line_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.customer_order.customer_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    line_code = Column(String(64), nullable=False)
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("mst.product.product_id"), nullable=False
    )
    quantity = Column(Numeric(18, 4), nullable=False)
    uom = Column(String(16), nullable=False, default="EA")
    status = Column(String(32), nullable=False, default="OPEN")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Dispatch(MesCoreBase):
    __tablename__ = "dispatch"
    __table_args__ = {"schema": "trn"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    customer_order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.customer_order.customer_order_id"),
    )
    production_lot_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.production_lot.production_lot_id"),
    )
    finished_goods_lot_no = Column(String(128))
    grade = Column(String(64))
    bag_count = Column(Numeric(18, 4))
    total_weight = Column(Numeric(18, 4))
    vehicle_no = Column(String(64))
    dispatch_date = Column(Date)
    invoice_ref = Column(String(128))
    destination = Column(Text)
    status = Column(String(32), nullable=False, default="PLANNED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
