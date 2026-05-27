"""mst.bom and mst.bom_item.

The Bill of Materials links a finished ``part`` to its constituent
``material`` requirements. The feasibility service can fold BOM totals into
its material availability check.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DECIMAL,
    ForeignKey,
    String,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class BOM(Base):
    __tablename__ = "bom"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bom_code = Column(String, nullable=False, unique=True, index=True)
    part_id = Column(BigInteger, ForeignKey("mst.part.id"))
    bom_version = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class BOMItem(Base):
    __tablename__ = "bom_item"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bom_id = Column(BigInteger, ForeignKey("mst.bom.id"))
    material_id = Column(BigInteger, ForeignKey("mst.material.id"))
    quantity_required = Column(DECIMAL(18, 4))
    unit_of_measure = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
