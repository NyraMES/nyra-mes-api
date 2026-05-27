"""mst.process_library — reusable manufacturing process definitions."""

from sqlalchemy import Boolean, Column, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.db.base import Base


class ProcessLibrary(Base):
    __tablename__ = "process_library"
    __table_args__ = {"schema": "mst"}

    process_id = Column(String, primary_key=True)
    process_code = Column(String, nullable=False, unique=True, index=True)
    process_name = Column(String, nullable=False)
    process_type = Column(String)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
