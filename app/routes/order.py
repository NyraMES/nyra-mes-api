"""Customer order routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.order import (
    OrderCreate,
    OrderLineCreate,
    OrderLineOut,
    OrderOut,
)
from app.services import order_service

router = APIRouter(tags=[Tags.ORDER])


@router.post(
    "/order",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create customer order (optionally with lines)",
)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    order, _lines = order_service.create_order(db, payload)
    return order


@router.post(
    "/order/{order_id}/line",
    response_model=OrderLineOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a line to an existing customer order",
)
def add_order_line(
    order_id: str,
    payload: OrderLineCreate,
    db: Session = Depends(get_db),
):
    return order_service.add_line(db, order_id, payload)


@router.get(
    "/orders",
    response_model=List[OrderOut],
    summary="List customer orders",
)
def list_orders(db: Session = Depends(get_db)):
    return order_service.list_orders(db)


@router.get(
    "/order-lines",
    response_model=List[OrderLineOut],
    summary="List all customer order lines (single query)",
)
@router.get(
    "/orders/lines",
    response_model=List[OrderLineOut],
    summary="Alias of /order-lines",
    include_in_schema=False,
)
def list_all_order_lines(db: Session = Depends(get_db)):
    return order_service.list_all_lines(db)


@router.get(
    "/order/{order_id}",
    response_model=OrderOut,
    summary="Get a customer order by ID",
)
def get_order(order_id: str, db: Session = Depends(get_db)):
    return order_service.get_order(db, order_id)


@router.get(
    "/order/{order_id}/lines",
    response_model=List[OrderLineOut],
    summary="List the lines for a customer order",
)
def list_order_lines(order_id: str, db: Session = Depends(get_db)):
    return order_service.list_lines(db, order_id)
