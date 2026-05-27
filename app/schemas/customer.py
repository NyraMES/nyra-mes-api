"""Customer DTOs.

The public field ``customer_id`` is the human-readable business code
(``CUST00001``). The DB-side surrogate PK is exposed as ``id`` (bigint).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CustomerCreate(BaseModel):
    customer_id: Optional[str] = None
    customer_name: str
    customer_type: Optional[str] = None


class CustomerOut(ORMModel):
    id: Optional[int] = None
    customer_id: str
    customer_name: str
    customer_type: Optional[str] = None
    created_at: Optional[datetime] = None
