"""trn.maintenance_event and trn.machine_downtime."""

from sqlalchemy import (
    BigInteger,
    Column,
    DECIMAL,
    ForeignKey,
    String,
    TIMESTAMP,
    Text,
)
from sqlalchemy.sql import func

from app.db.base import Base


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_event"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    machine_id = Column(BigInteger, ForeignKey("mst.machine.id"))
    event_type = Column(String)
    event_status = Column(String)
    reported_at = Column(TIMESTAMP)
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)
    reported_by = Column(String)
    issue_description = Column(Text)
    action_taken = Column(Text)
    downtime_minutes = Column(DECIMAL(18, 4))


class MachineDowntime(Base):
    __tablename__ = "machine_downtime"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    machine_id = Column(BigInteger, ForeignKey("mst.machine.id"))
    work_order_id = Column(BigInteger, ForeignKey("trn.work_order.id"))
    downtime_reason = Column(String)
    downtime_start = Column(TIMESTAMP)
    downtime_end = Column(TIMESTAMP)
    downtime_minutes = Column(DECIMAL(18, 4))
    created_at = Column(TIMESTAMP, server_default=func.now())
