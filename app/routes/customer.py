"""Customer routes - thin layer over :mod:`app.services.customer_service`."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.customer import CustomerCreate, CustomerOut
from app.services import customer_service

router = APIRouter(prefix="/customer", tags=[Tags.CUSTOMER])


@router.post(
    "",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create customer",
)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    return customer_service.create_customer(db, payload)


@router.get(
    "",
    response_model=List[CustomerOut],
    summary="List customers",
)
def list_customers(db: Session = Depends(get_db)):
    return customer_service.list_customers(db)


@router.get(
    "/{customer_id}",
    response_model=CustomerOut,
    summary="Get customer by ID",
)
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    return customer_service.get_customer(db, customer_id)
