"""trn.customer_order and trn.customer_order_line."""

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


class CustomerOrder(Base):
    __tablename__ = "customer_order"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_code = Column(String, nullable=False, unique=True, index=True)
    customer_id = Column(BigInteger, ForeignKey("mst.customer.id"))
    order_date = Column(TIMESTAMP)
    delivery_date = Column(TIMESTAMP)
    status = Column(String, default="Created")
    created_at = Column(TIMESTAMP, server_default=func.now())


class CustomerOrderLine(Base):
    __tablename__ = "customer_order_line"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_line_code = Column(String, nullable=False, unique=True, index=True)
    order_id = Column(BigInteger, ForeignKey("trn.customer_order.id"))
    part_id = Column(BigInteger, ForeignKey("mst.part.id"))
    quantity = Column(DECIMAL(18, 4), nullable=False)
    status = Column(String, default="Planned")
    created_at = Column(TIMESTAMP, server_default=func.now())
