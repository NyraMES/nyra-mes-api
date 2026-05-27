"""Production order routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.production import (
    ProductionLotOut,
    ProductionOrderCreate,
    ProductionOrderOut,
    ProductionOrderWithLotsCreate,
)
from app.services import production_service

router = APIRouter(tags=[Tags.PRODUCTION])


@router.post(
    "/production-order",
    response_model=ProductionOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a production order from a customer order line",
)
def create_production_order(
    payload: ProductionOrderCreate, db: Session = Depends(get_db)
):
    return production_service.create_production_order(db, payload)


@router.get(
    "/production-orders",
    response_model=List[ProductionOrderOut],
    summary="List production orders",
)
def list_production_orders(db: Session = Depends(get_db)):
    return production_service.list_production_orders(db)


@router.get(
    "/production-order/{production_order_id}",
    response_model=ProductionOrderOut,
    summary="Get a production order",
)
def get_production_order(
    production_order_id: str, db: Session = Depends(get_db)
):
    return production_service.get_production_order(db, production_order_id)


@router.post(
    "/production-order-with-lots",
    status_code=status.HTTP_201_CREATED,
    summary="Atomically create production order + lots in one call",
)
def create_production_order_with_lots(
    payload: ProductionOrderWithLotsCreate,
    db: Session = Depends(get_db),
):
    po, lots = production_service.create_production_order_with_lots(db, payload)
    return {
        "production_order": po.model_dump(),
        "lots": [lot.model_dump() for lot in lots],
    }
