"""trn.feasibility_gate - persisted feasibility verdict per lot.

This is a write-target for the feasibility service so that downstream
services can query the latest gate without re-running the full check.
The aggregated read view ``trn.v_feasibility_summary`` joins this table
with the live availability tables.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    String,
    TIMESTAMP,
    Text,
)

from app.db.base import Base


class FeasibilityGate(Base):
    __tablename__ = "feasibility_gate"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    lot_id = Column(BigInteger, ForeignKey("trn.production_lot.id"))
    material_status = Column(String)
    machine_status = Column(String)
    tool_status = Column(String)
    workforce_status = Column(String)
    overall_status = Column(String)
    blocked_reason = Column(Text)
    checked_at = Column(TIMESTAMP)
