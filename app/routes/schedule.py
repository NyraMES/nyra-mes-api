"""Scheduling routes.

Scheduling is the workflow gate between feasibility and work-order release.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.schedule import ScheduleCreate, ScheduleOut
from app.services import schedule_service

router = APIRouter(tags=[Tags.SCHEDULING])


@router.post(
    "/schedule",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a single (lot, operation) - requires feasibility = OK",
)
def create_schedule(payload: ScheduleCreate, db: Session = Depends(get_db)):
    return schedule_service.create_schedule(db, payload)


@router.get(
    "/schedules",
    response_model=List[ScheduleOut],
    summary="List production schedules",
)
def list_schedules(db: Session = Depends(get_db)):
    return schedule_service.list_schedules(db)


@router.get(
    "/schedule/{schedule_id}",
    response_model=ScheduleOut,
    summary="Get a single schedule",
)
def get_schedule(schedule_id: str, db: Session = Depends(get_db)):
    return schedule_service.get_schedule(db, schedule_id)


@router.get(
    "/lot/{lot_id}/schedule-plan",
    summary=(
        "Pre-filled scheduling plan for a lot - lists every routing operation "
        "with a suggested machine + work center + estimated duration. Used by "
        "the Scheduling Board UI to auto-fill the form."
    ),
)
def get_lot_schedule_plan(lot_id: str, db: Session = Depends(get_db)):
    return schedule_service.get_schedule_plan(db, lot_id)
