"""Quality master + transactional models.

mst.defect, mst.inspection_plan, mst.inspection_parameter,
trn.inspection_result, trn.inspection_result_parameter, trn.ncr.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DECIMAL,
    ForeignKey,
    String,
    TIMESTAMP,
    Text,
)
from sqlalchemy.sql import func

from app.db.base import Base


class Defect(Base):
    __tablename__ = "defect"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    defect_code = Column(String, nullable=False, unique=True, index=True)
    defect_name = Column(String)
    defect_type = Column(String)
    severity = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())


class InspectionPlan(Base):
    __tablename__ = "inspection_plan"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    inspection_plan_code = Column(String, nullable=False, unique=True, index=True)
    part_id = Column(BigInteger, ForeignKey("mst.part.id"))
    routing_operation_id = Column(BigInteger, ForeignKey("mst.routing_operation.id"))
    plan_name = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class InspectionParameter(Base):
    __tablename__ = "inspection_parameter"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    inspection_plan_id = Column(BigInteger, ForeignKey("mst.inspection_plan.id"))
    parameter_name = Column(String)
    specification_min = Column(DECIMAL(18, 4))
    specification_max = Column(DECIMAL(18, 4))
    unit_of_measure = Column(String)
    is_mandatory = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class InspectionResult(Base):
    __tablename__ = "inspection_result"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    inspection_code = Column(String, nullable=False, unique=True, index=True)
    work_order_id = Column(BigInteger, ForeignKey("trn.work_order.id"))
    lot_id = Column(BigInteger, ForeignKey("trn.production_lot.id"))
    inspection_plan_id = Column(BigInteger, ForeignKey("mst.inspection_plan.id"))
    inspected_quantity = Column(DECIMAL(18, 4))
    accepted_quantity = Column(DECIMAL(18, 4))
    rejected_quantity = Column(DECIMAL(18, 4))
    inspection_status = Column(String)
    inspected_at = Column(TIMESTAMP)


class InspectionResultParameter(Base):
    __tablename__ = "inspection_result_parameter"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    inspection_result_id = Column(BigInteger, ForeignKey("trn.inspection_result.id"))
    inspection_parameter_id = Column(BigInteger, ForeignKey("mst.inspection_parameter.id"))
    observed_value = Column(DECIMAL(18, 4))
    result_status = Column(String)


class NCR(Base):
    __tablename__ = "ncr"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ncr_code = Column(String, nullable=False, unique=True, index=True)
    inspection_result_id = Column(BigInteger, ForeignKey("trn.inspection_result.id"))
    defect_id = Column(BigInteger, ForeignKey("mst.defect.id"))
    rejected_quantity = Column(DECIMAL(18, 4))
    disposition = Column(String)
    root_cause = Column(Text)
    corrective_action = Column(Text)
    status = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
