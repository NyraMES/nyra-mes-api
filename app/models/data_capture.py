"""Data capture master + transaction tables for dynamic shop-floor forms."""

from sqlalchemy import (
    Boolean,
    Column,
    DECIMAL,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class DataCaptureTemplate(Base):
    __tablename__ = "data_capture_template"
    __table_args__ = {"schema": "mst"}

    template_id = Column(String, primary_key=True)
    process_id = Column(String, ForeignKey("mst.process_library.process_id"))
    template_name = Column(String, nullable=False)
    template_sequence = Column(Integer)
    capture_stage = Column(String)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class DataCaptureField(Base):
    __tablename__ = "data_capture_field"
    __table_args__ = {"schema": "mst"}

    field_id = Column(String, primary_key=True)
    template_id = Column(String, ForeignKey("mst.data_capture_template.template_id"))
    field_sequence = Column(Integer, nullable=False)
    field_name = Column(String, nullable=False)
    field_label = Column(String, nullable=False)
    field_type = Column(String)
    unit_of_measure = Column(String)
    is_mandatory = Column(Boolean, default=False)
    min_value = Column(DECIMAL(18, 4))
    max_value = Column(DECIMAL(18, 4))
    dropdown_values = Column(Text)
    ontology_property = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())


class OperationDataCapture(Base):
    __tablename__ = "operation_data_capture"
    __table_args__ = {"schema": "trn"}

    capture_id = Column(String, primary_key=True)
    work_order_id = Column(String, ForeignKey("trn.work_order.work_order_code"))
    routing_operation_id = Column(
        String, ForeignKey("mst.routing_operation.operation_code")
    )
    template_id = Column(String, ForeignKey("mst.data_capture_template.template_id"))
    captured_by = Column(String)
    captured_at = Column(TIMESTAMP, server_default=func.now())


class OperationDataCaptureValue(Base):
    __tablename__ = "operation_data_capture_value"
    __table_args__ = {"schema": "trn"}

    capture_value_id = Column(String, primary_key=True)
    capture_id = Column(String, ForeignKey("trn.operation_data_capture.capture_id"))
    field_id = Column(String, ForeignKey("mst.data_capture_field.field_id"))
    value_sequence = Column(Integer)
    field_value = Column(Text)
    validation_status = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
