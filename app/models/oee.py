"""trn.oee_daily_summary."""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DECIMAL,
    ForeignKey,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class OEEDailySummary(Base):
    __tablename__ = "oee_daily_summary"
    __table_args__ = {"schema": "trn"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    machine_id = Column(BigInteger, ForeignKey("mst.machine.id"))
    oee_date = Column(Date)
    planned_production_minutes = Column(DECIMAL(18, 4))
    downtime_minutes = Column(DECIMAL(18, 4))
    ideal_cycle_time_minutes = Column(DECIMAL(18, 4))
    total_quantity = Column(DECIMAL(18, 4))
    good_quantity = Column(DECIMAL(18, 4))
    availability_percent = Column(DECIMAL(7, 4))
    performance_percent = Column(DECIMAL(7, 4))
    quality_percent = Column(DECIMAL(7, 4))
    oee_percent = Column(DECIMAL(7, 4))
    created_at = Column(TIMESTAMP, server_default=func.now())
