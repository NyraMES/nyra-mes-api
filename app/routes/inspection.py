"""Inspection routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.quality import (
    InspectionParameterResultCreate,
    InspectionParameterResultOut,
    InspectionResultCreate,
    InspectionResultOut,
)
from app.services import inspection_service

router = APIRouter(tags=[Tags.INSPECTION])


@router.post(
    "/inspection-result",
    response_model=InspectionResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record an inspection result",
)
def create_inspection_result(
    payload: InspectionResultCreate, db: Session = Depends(get_db)
):
    return inspection_service.create_inspection_result(db, payload)


@router.post(
    "/inspection-parameter-result",
    response_model=InspectionParameterResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a per-parameter measurement for an inspection result",
)
def create_parameter_result(
    payload: InspectionParameterResultCreate, db: Session = Depends(get_db)
):
    return inspection_service.create_parameter_result(db, payload)


@router.get(
    "/inspection-results",
    response_model=List[InspectionResultOut],
    summary="List inspection results",
)
def list_inspection_results(db: Session = Depends(get_db)):
    return inspection_service.list_inspection_results(db)


@router.get(
    "/lot/{lot_id}/inspection-results",
    response_model=List[InspectionResultOut],
    summary="List inspections recorded for a lot",
)
def list_inspections_for_lot(lot_id: str, db: Session = Depends(get_db)):
    return inspection_service.list_inspection_results_for_lot(db, lot_id)
