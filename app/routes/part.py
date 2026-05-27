"""Part master routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.part import PartCreate, PartOut
from app.schemas.routing import PartRoutingOut, RoutingOut
from app.services import part_service

router = APIRouter(prefix="/part", tags=[Tags.PART])


@router.post(
    "",
    response_model=PartOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create part",
)
def create_part(payload: PartCreate, db: Session = Depends(get_db)):
    return part_service.create_part(db, payload)


@router.get(
    "",
    response_model=List[PartOut],
    summary="List parts",
)
def list_parts(db: Session = Depends(get_db)):
    return part_service.list_parts(db)


@router.get(
    "/{part_id}",
    response_model=PartOut,
    summary="Get part by ID",
)
def get_part(part_id: str, db: Session = Depends(get_db)):
    return part_service.get_part(db, part_id)


# REST-style aliases for route entry screens (/parts)
parts_router = APIRouter(prefix="/parts", tags=[Tags.PART])


@parts_router.get(
    "",
    response_model=List[PartOut],
    summary="List parts (route entry alias)",
)
def list_parts_plural(db: Session = Depends(get_db)):
    return part_service.list_parts(db)


@parts_router.post(
    "",
    response_model=PartOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create part (route entry alias)",
)
def create_part_plural(payload: PartCreate, db: Session = Depends(get_db)):
    return part_service.create_part(db, payload)


@parts_router.get(
    "/{part_id}/routing",
    response_model=PartRoutingOut,
    summary="Get active routing and sequenced operations for a part",
)
def get_part_routing(part_id: str, db: Session = Depends(get_db)):
    from app.services import routing_service

    return routing_service.get_part_routing(db, part_id)


@parts_router.get(
    "/{part_id}/routings",
    response_model=List[RoutingOut],
    summary="List routings for a part (route entry alias)",
    include_in_schema=False,
)
def list_part_routings_plural(part_id: str, db: Session = Depends(get_db)):
    from app.services import routing_service

    return routing_service.list_routings_for_part(db, part_id)
