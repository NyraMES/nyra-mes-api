"""Execution, quality, and KG models in nyra_mes_core — all tenant-scoped."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.mes_core_base import MesCoreBase
from app.models.mes_core.scoping import workspace_id_column


class OperationExecution(MesCoreBase):
    __tablename__ = "operation_execution"
    __table_args__ = {"schema": "exec"}

    execution_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    execution_code = Column(String(64), nullable=False)
    production_lot_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.production_lot.production_lot_id"),
        nullable=False,
    )
    routing_operation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mst.routing_operation.routing_operation_id"),
        nullable=False,
    )
    equipment_id = Column(UUID(as_uuid=True), ForeignKey("mst.equipment.equipment_id"))
    status = Column(String(32), nullable=False, default="NOT_STARTED")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class ParameterReading(MesCoreBase):
    __tablename__ = "parameter_reading"
    __table_args__ = {"schema": "exec"}

    parameter_reading_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    execution_id = Column(
        UUID(as_uuid=True),
        ForeignKey("exec.operation_execution.execution_id", ondelete="CASCADE"),
        nullable=False,
    )
    parameter_code = Column(String(128), nullable=False)
    parameter_name = Column(String(256))
    reading_value = Column(Numeric(18, 6))
    reading_text = Column(Text)
    uom = Column(String(16))
    recorded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class QualityCheck(MesCoreBase):
    __tablename__ = "quality_check"
    __table_args__ = {"schema": "qms"}

    quality_check_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    check_code = Column(String(64), nullable=False)
    production_lot_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trn.production_lot.production_lot_id"),
        nullable=False,
    )
    check_type = Column(String(64), nullable=False, default="IN_PROCESS")
    status = Column(String(32), nullable=False, default="OPEN")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class QualityResult(MesCoreBase):
    __tablename__ = "quality_result"
    __table_args__ = {"schema": "qms"}

    quality_result_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    quality_check_id = Column(
        UUID(as_uuid=True),
        ForeignKey("qms.quality_check.quality_check_id", ondelete="CASCADE"),
        nullable=False,
    )
    characteristic_code = Column(String(128), nullable=False)
    characteristic_name = Column(String(256))
    measured_value = Column(Numeric(18, 6))
    measured_text = Column(Text)
    uom = Column(String(16))
    result_status = Column(String(32), nullable=False, default="PASS")
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class TripleStoreStaging(MesCoreBase):
    __tablename__ = "triple_store_staging"
    __table_args__ = {"schema": "kg"}

    triple_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_id = workspace_id_column()
    subject_uri = Column(Text, nullable=False)
    predicate_uri = Column(Text, nullable=False)
    object_uri = Column(Text)
    object_literal = Column(Text)
    object_datatype = Column(String(128))
    source_table = Column(String(128))
    source_id = Column(UUID(as_uuid=True))
    export_status = Column(String(32), nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
