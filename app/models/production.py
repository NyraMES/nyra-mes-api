"""trn.production_order and trn.production_lot."""

from sqlalchemy import (
    BigInteger,
    Column,
    DECIMAL,
    ForeignKey,
    String,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class ProductionOrder(Base):
    __tablename__ = "production_order"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    production_order_code = Column(String, nullable=False, unique=True, index=True)
    order_line_id = Column(BigInteger, ForeignKey("trn.customer_order_line.id"))
    planned_quantity = Column(DECIMAL(18, 4))
    planned_start_date = Column(TIMESTAMP)
    planned_end_date = Column(TIMESTAMP)
    status = Column(String, default="Planned")
    created_at = Column(TIMESTAMP, server_default=func.now())


class ProductionLot(Base):
    __tablename__ = "production_lot"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lot_code = Column(String, nullable=False, unique=True, index=True)
    production_order_id = Column(BigInteger, ForeignKey("trn.production_order.id"))
    lot_quantity = Column(DECIMAL(18, 4))
    status = Column(String, default="Created")
    created_at = Column(TIMESTAMP, server_default=func.now())
