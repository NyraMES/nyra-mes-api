"""Customer-order DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class OrderLineCreate(BaseModel):
    """Public payload for creating a customer order line.

    ``order_line_id`` is the *business* code (e.g. ``ORDL00007``). Leaving it
    blank lets the backend auto-generate one from the ``trn.order_line_seq``.
    """

    order_line_id: Optional[str] = None
    part_id: str
    quantity: Decimal
    status: Optional[str] = "Planned"


class OrderLineOut(ORMModel):
    id: Optional[int] = None
    order_line_id: str
    order_id: str
    part_id: Optional[str] = None
    quantity: Decimal
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class OrderCreate(BaseModel):
    order_id: Optional[str] = None
    customer_id: str
    order_date: Optional[datetime] = None
    delivery_date: datetime
    status: Optional[str] = "Created"
    lines: Optional[List[OrderLineCreate]] = None


class OrderOut(ORMModel):
    id: Optional[int] = None
    order_id: str
    customer_id: Optional[str] = None
    order_date: Optional[datetime] = None
    delivery_date: Optional[datetime] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
