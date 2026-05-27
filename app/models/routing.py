"""mst.routing, mst.routing_operation, mst.operation_resource_requirement.

``operation_resource_requirement`` declares the materials/machines/tools/
workforce roles that an operation expects (with required quantities). The
feasibility service uses these rows to decide whether a lot can start.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DECIMAL,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class Routing(Base):
    __tablename__ = "routing"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    routing_code = Column(String, nullable=False, unique=True, index=True)
    part_id = Column(BigInteger, ForeignKey("mst.part.id"))
    routing_version = Column(String)
    process_type = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class RoutingOperation(Base):
    __tablename__ = "routing_operation"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    operation_code = Column(String, nullable=False, unique=True, index=True)
    routing_id = Column(BigInteger, ForeignKey("mst.routing.id"))
    operation_sequence = Column(Integer, nullable=False)
    operation_name = Column(String, nullable=False)
    process_id = Column(String, ForeignKey("mst.process_library.process_id"))
    standard_cycle_time_minutes = Column(DECIMAL(18, 4))
    inspection_required = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.now())


class OperationResourceRequirement(Base):
    __tablename__ = "operation_resource_requirement"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    routing_operation_id = Column(BigInteger, ForeignKey("mst.routing_operation.id"))
    required_resource_type = Column(String)  # 'material' | 'machine' | 'tool' | 'workforce'
    required_resource_id = Column(BigInteger)  # FK target depends on type
    required_quantity = Column(DECIMAL(18, 4))
    is_mandatory = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
