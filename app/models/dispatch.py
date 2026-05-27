"""trn.dispatch and trn.dispatch_line."""

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


class Dispatch(Base):
    __tablename__ = "dispatch"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dispatch_code = Column(String, nullable=False, unique=True, index=True)
    customer_id = Column(BigInteger, ForeignKey("mst.customer.id"))
    order_id = Column(BigInteger, ForeignKey("trn.customer_order.id"))
    dispatch_date = Column(TIMESTAMP)
    vehicle_number = Column(String)
    transporter_name = Column(String)
    dispatch_status = Column(String, default="Ready")
    remarks = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())


class DispatchLine(Base):
    __tablename__ = "dispatch_line"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dispatch_id = Column(BigInteger, ForeignKey("trn.dispatch.id"))
    lot_id = Column(BigInteger, ForeignKey("trn.production_lot.id"))
    part_id = Column(BigInteger, ForeignKey("mst.part.id"))
    dispatch_quantity = Column(DECIMAL(18, 4))
    accepted_quantity = Column(DECIMAL(18, 4))
    rejected_quantity = Column(DECIMAL(18, 4))
    created_at = Column(TIMESTAMP, server_default=func.now())
