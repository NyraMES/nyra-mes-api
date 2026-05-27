"""Maintenance routes (events + downtime)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.maintenance import (
    MachineDowntimeCreate,
    MachineDowntimeOut,
    MaintenanceEventCreate,
    MaintenanceEventOut,
)
from app.services import oee_service

router = APIRouter(tags=[Tags.MAINTENANCE])


@router.post(
    "/maintenance-event",
    response_model=MaintenanceEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a maintenance event for a machine",
)
def create_maintenance_event(
    payload: MaintenanceEventCreate, db: Session = Depends(get_db)
):
    return oee_service.create_maintenance(db, payload)


@router.get(
    "/maintenance-events",
    response_model=List[MaintenanceEventOut],
    summary="List maintenance events",
)
def list_maintenance_events(db: Session = Depends(get_db)):
    return oee_service.list_maintenance(db)


@router.post(
    "/machine-downtime",
    response_model=MachineDowntimeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a machine downtime window",
)
def create_machine_downtime(
    payload: MachineDowntimeCreate, db: Session = Depends(get_db)
):
    return oee_service.create_downtime(db, payload)


@router.get(
    "/machine-downtimes",
    response_model=List[MachineDowntimeOut],
    summary="List machine downtime entries",
)
def list_machine_downtimes(db: Session = Depends(get_db)):
    return oee_service.list_downtime(db)
