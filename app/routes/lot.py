"""Lot routes - lot split, lot listing, lot status."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.production import (
    LotSplitRequest,
    ProductionLotCreate,
    ProductionLotOut,
)
from app.services import production_service

router = APIRouter(tags=[Tags.LOT])


@router.post(
    "/production-order/{production_order_id}/lots/split",
    response_model=List[ProductionLotOut],
    status_code=status.HTTP_201_CREATED,
    summary="Split a production order into lots (sum must equal planned qty)",
)
def split_lots(
    production_order_id: str,
    payload: LotSplitRequest,
    db: Session = Depends(get_db),
):
    _, lots = production_service.split_lots(db, production_order_id, payload)
    return lots


@router.post(
    "/production-lot",
    response_model=ProductionLotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a single production lot under an existing production order",
)
def create_lot(payload: ProductionLotCreate, db: Session = Depends(get_db)):
    return production_service.create_lot(db, payload)


@router.get(
    "/production-order/{production_order_id}/lots",
    response_model=List[ProductionLotOut],
    summary="List lots for a production order",
)
def list_lots(production_order_id: str, db: Session = Depends(get_db)):
    return production_service.list_lots_for_order(db, production_order_id)


@router.get(
    "/lots",
    response_model=List[ProductionLotOut],
    summary="List every production lot across all production orders",
)
def list_all_lots(db: Session = Depends(get_db)):
    return production_service.list_all_lots(db)


@router.get(
    "/production-lots",
    response_model=List[ProductionLotOut],
    summary="List every production lot (legacy path; alias of /lots)",
)
def list_all_lots_legacy(db: Session = Depends(get_db)):
    return production_service.list_all_lots(db)


@router.get(
    "/lot/{lot_id}",
    response_model=ProductionLotOut,
    summary="Get a single lot by ID",
)
def get_lot(lot_id: str, db: Session = Depends(get_db)):
    return production_service.get_lot(db, lot_id)


@router.get(
    "/production-lot/{lot_id}",
    response_model=ProductionLotOut,
    summary="Get a production lot (legacy path)",
    include_in_schema=False,
)
def get_lot_legacy(lot_id: str, db: Session = Depends(get_db)):
    return production_service.get_lot(db, lot_id)
