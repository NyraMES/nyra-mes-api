"""Master-data resources: work_center, machine, tool, material, workforce_role."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DECIMAL,
    ForeignKey,
    Integer,
    String,
    TIMESTAMP,
)
from sqlalchemy.sql import func

from app.db.base import Base


class WorkCenter(Base):
    __tablename__ = "work_center"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    work_center_code = Column(String, nullable=False, unique=True, index=True)
    work_center_name = Column(String, nullable=False)
    process_type = Column(String)
    location = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Machine(Base):
    __tablename__ = "machine"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    machine_code = Column(String, nullable=False, unique=True, index=True)
    work_center_id = Column(BigInteger, ForeignKey("mst.work_center.id"))
    machine_name = Column(String, nullable=False)
    machine_type = Column(String)
    machine_status = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Tool(Base):
    __tablename__ = "tool"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tool_code = Column(String, nullable=False, unique=True, index=True)
    tool_name = Column(String, nullable=False)
    tool_type = Column(String)
    tool_status = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())


class Material(Base):
    __tablename__ = "material"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    material_code = Column(String, nullable=False, unique=True, index=True)
    material_name = Column(String, nullable=False)
    material_type = Column(String)
    unit_of_measure = Column(String)
    available_quantity = Column(DECIMAL(18, 4))
    created_at = Column(TIMESTAMP, server_default=func.now())


class WorkforceRole(Base):
    __tablename__ = "workforce_role"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    role_code = Column(String, nullable=False, unique=True, index=True)
    role_name = Column(String, nullable=False)
    skill_level = Column(String)
    available_count = Column(Integer)
    created_at = Column(TIMESTAMP, server_default=func.now())
