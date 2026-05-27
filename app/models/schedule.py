"""trn.production_schedule."""

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    String,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class ProductionSchedule(Base):
    __tablename__ = "production_schedule"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    schedule_code = Column(String, nullable=False, unique=True, index=True)
    lot_id = Column(BigInteger, ForeignKey("trn.production_lot.id"))
    routing_operation_id = Column(BigInteger, ForeignKey("mst.routing_operation.id"))
    planned_start_time = Column(TIMESTAMP)
    planned_end_time = Column(TIMESTAMP)
    assigned_work_center_id = Column(BigInteger, ForeignKey("mst.work_center.id"))
    assigned_machine_id = Column(BigInteger, ForeignKey("mst.machine.id"))
    schedule_status = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
