"""Master-data resource listings (picker endpoints used by the Routing Master)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.resource import (
    MachineOut,
    MaterialOut,
    ToolOut,
    WorkCenterOut,
    WorkforceRoleOut,
)
from app.services import resource_service

router = APIRouter(tags=[Tags.ROUTING])


@router.get(
    "/work-centers",
    response_model=List[WorkCenterOut],
    summary="List work centers",
)
def list_work_centers(db: Session = Depends(get_db)):
    return resource_service.list_work_centers(db)


@router.get(
    "/machines",
    response_model=List[MachineOut],
    summary="List machines",
)
def list_machines(db: Session = Depends(get_db)):
    return resource_service.list_machines(db)


@router.get(
    "/tools",
    response_model=List[ToolOut],
    summary="List tools",
)
def list_tools(db: Session = Depends(get_db)):
    return resource_service.list_tools(db)


@router.get(
    "/materials",
    response_model=List[MaterialOut],
    summary="List materials",
)
def list_materials(db: Session = Depends(get_db)):
    return resource_service.list_materials(db)


@router.get(
    "/workforce-roles",
    response_model=List[WorkforceRoleOut],
    summary="List workforce roles",
)
def list_workforce_roles(db: Session = Depends(get_db)):
    return resource_service.list_workforce_roles(db)
