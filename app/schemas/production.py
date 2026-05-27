"""Production-order and production-lot DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ProductionLotCreate(BaseModel):
    lot_id: Optional[str] = None
    production_order_id: Optional[str] = None
    lot_quantity: Decimal
    status: Optional[str] = "Created"


class ProductionLotOut(ORMModel):
    id: Optional[int] = None
    lot_id: str
    production_order_id: Optional[str] = None
    lot_quantity: Optional[Decimal] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class LotSplitRequest(BaseModel):
    """Body for ``POST /production-order/{id}/lots/split``."""

    lots: List[ProductionLotCreate]


class ProductionOrderCreate(BaseModel):
    """``order_line_id`` is the business code ``ORDLxxxxx``."""

    production_order_id: Optional[str] = None
    order_line_id: str
    planned_quantity: Decimal
    planned_start_date: Optional[datetime] = None
    planned_end_date: Optional[datetime] = None
    status: Optional[str] = "Planned"


class ProductionOrderWithLotsCreate(ProductionOrderCreate):
    lots: List[ProductionLotCreate]


class ProductionOrderOut(ORMModel):
    id: Optional[int] = None
    production_order_id: str
    order_line_id: Optional[str] = None
    planned_quantity: Optional[Decimal] = None
    planned_start_date: Optional[datetime] = None
    planned_end_date: Optional[datetime] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
