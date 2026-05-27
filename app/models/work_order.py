"""trn.work_order and trn.work_order_event.

Note: ``trn.lot_operation_execution`` is intentionally NOT modelled here -
the DB schema does not include it. Per-operation execution data is captured
via ``trn.work_order`` rows (one per scheduled operation) and supplemented
with append-only event rows in ``trn.work_order_event``.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DECIMAL,
    ForeignKey,
    String,
    TIMESTAMP,
    Text,
)

from app.db.base import Base


class WorkOrder(Base):
    __tablename__ = "work_order"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    work_order_code = Column(String, nullable=False, unique=True, index=True)
    schedule_id = Column(BigInteger, ForeignKey("trn.production_schedule.id"))
    lot_id = Column(BigInteger, ForeignKey("trn.production_lot.id"))
    routing_operation_id = Column(BigInteger, ForeignKey("mst.routing_operation.id"))
    work_order_status = Column(String)
    released_at = Column(TIMESTAMP)
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)
    actual_output_quantity = Column(DECIMAL(18, 4))
    scrap_quantity = Column(DECIMAL(18, 4))
    rework_quantity = Column(DECIMAL(18, 4))
    # operator / machine / downtime are stored in work_order_event remarks and
    # trn.machine_downtime until optional columns are added via migration script.


class WorkOrderEvent(Base):
    __tablename__ = "work_order_event"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id = Column(BigInteger, ForeignKey("trn.work_order.id"))
    event_type = Column(String)
    event_time = Column(TIMESTAMP)
    remarks = Column(Text)
