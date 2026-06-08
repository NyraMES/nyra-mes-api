"""Master-data models in nyra_mes_core (mst.* schema) — all tenant-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.mes_core_base import MesCoreBase
from app.models.mes_core.scoping import workspace_id_column


class Customer(MesCoreBase):
    __tablename__ = "customer"
    __table_args__ = {"schema": "mst"}

    customer_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    customer_code = Column(String(64), nullable=False)
    customer_name = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Supplier(MesCoreBase):
    __tablename__ = "supplier"
    __table_args__ = {"schema": "mst"}

    supplier_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    supplier_code = Column(String(64), nullable=False)
    supplier_name = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Product(MesCoreBase):
    __tablename__ = "product"
    __table_args__ = {"schema": "mst"}

    product_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    product_code = Column(String(64), nullable=False)
    product_name = Column(String(256), nullable=False)
    product_type = Column(String(64))
    uom = Column(String(16), nullable=False, default="EA")
    status = Column(String(32), nullable=False, default="ACTIVE")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Resource(MesCoreBase):
    __tablename__ = "resource"
    __table_args__ = {"schema": "mst"}

    resource_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    resource_code = Column(String(64), nullable=False)
    resource_name = Column(String(256), nullable=False)
    resource_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Equipment(MesCoreBase):
    __tablename__ = "equipment"
    __table_args__ = {"schema": "mst"}

    equipment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    equipment_code = Column(String(64), nullable=False)
    equipment_name = Column(String(256), nullable=False)
    resource_id = Column(UUID(as_uuid=True), ForeignKey("mst.resource.resource_id"))
    equipment_type = Column(String(64))
    status = Column(String(32), nullable=False, default="ACTIVE")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Routing(MesCoreBase):
    __tablename__ = "routing"
    __table_args__ = {"schema": "mst"}

    routing_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    routing_code = Column(String(64), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("mst.product.product_id"), nullable=True)
    routing_version = Column(String(32), nullable=False, default="1")
    process_family = Column(String(64))
    is_active = Column(Boolean, nullable=False, default=True)
    industry_template_code = Column(String(64))
    source_template_code = Column(String(64))
    is_template_route = Column(Boolean, nullable=False, default=False)
    is_template_copy = Column(Boolean, nullable=False, default=False)
    is_customized = Column(Boolean, nullable=False, default=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class RoutingOperation(MesCoreBase):
    __tablename__ = "routing_operation"
    __table_args__ = {"schema": "mst"}

    routing_operation_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    routing_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mst.routing.routing_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation_code = Column(String(64), nullable=False)
    operation_sequence = Column(Integer, nullable=False)
    operation_name = Column(String(256), nullable=False)
    standard_cycle_min = Column(Numeric(12, 4))
    industry_template_code = Column(String(64))
    source_template_operation_code = Column(String(64))
    operation_seq = Column(Integer)
    operation_type = Column(String(64))
    is_quality_gate = Column(Boolean, nullable=False, default=False)
    is_feasibility_gate = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_customized = Column(Boolean, nullable=False, default=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class RoutingOperationParameter(MesCoreBase):
    __tablename__ = "routing_operation_parameter"
    __table_args__ = {"schema": "mst"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    routing_operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mst.routing_operation.routing_operation_id", ondelete="CASCADE"),
        nullable=False,
    )
    parameter_code = Column(String(64))
    parameter_name = Column(String(256))
    data_type = Column(String(32))
    unit = Column(String(32))
    min_value = Column(Numeric(18, 6))
    max_value = Column(Numeric(18, 6))
    is_mandatory = Column(Boolean, nullable=False, default=False)
    reading_frequency = Column(String(64))
    display_order = Column(Integer)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class OperationResourceRequirement(MesCoreBase):
    __tablename__ = "operation_resource_requirement"
    __table_args__ = {"schema": "mst"}

    requirement_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    routing_operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mst.routing_operation.routing_operation_id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mst.resource.resource_id"),
        nullable=False,
    )
    requirement_type = Column(String(32), nullable=False, default="PRIMARY")
    quantity = Column(Numeric(18, 4), nullable=False, default=1)
    uom = Column(String(16), nullable=False, default="EA")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
