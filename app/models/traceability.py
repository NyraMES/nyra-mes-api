"""trn.traceability_closure."""

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    String,
    TIMESTAMP,
    Text,
)

from app.db.base import Base


class TraceabilityClosure(Base):
    __tablename__ = "traceability_closure"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lot_id = Column(BigInteger, ForeignKey("trn.production_lot.id"))
    order_id = Column(BigInteger, ForeignKey("trn.customer_order.id"))
    production_order_id = Column(BigInteger, ForeignKey("trn.production_order.id"))
    final_quality_status = Column(String)
    dispatch_id = Column(BigInteger, ForeignKey("trn.dispatch.id"))
    closure_status = Column(String)
    closed_at = Column(TIMESTAMP)
    remarks = Column(Text)
