"""mst.part model."""

from sqlalchemy import BigInteger, Column, String, TIMESTAMP
from sqlalchemy.sql import func

from app.db.base import Base


class Part(Base):
    __tablename__ = "part"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    part_code = Column(String, nullable=False, unique=True, index=True)
    part_name = Column(String, nullable=False)
    part_type = Column(String)
    unit_of_measure = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
