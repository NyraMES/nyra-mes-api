"""mst.customer model.

Schema notes
------------
The DB uses a surrogate ``id`` (BIGINT) as the PK and an opaque
``customer_code`` (varchar) as the human-friendly business identifier
exposed by the API. Services translate between the two at FK boundaries.
"""

from sqlalchemy import BigInteger, Column, String, TIMESTAMP
from sqlalchemy.sql import func

from app.db.base import Base


class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = {"schema": "mst"}

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    customer_code = Column(String, nullable=False, unique=True, index=True)
    customer_name = Column(String, nullable=False)
    customer_type = Column(String)
    created_at = Column(TIMESTAMP, server_default=func.now())
