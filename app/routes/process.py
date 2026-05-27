"""Process library routes."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.common import MessageResponse
from app.schemas.process import ProcessCreate, ProcessResponse, ProcessUpdate
from app.services import process_service

router = APIRouter(tags=[Tags.PROCESS])


@router.get(
    "/processes",
    response_model=List[ProcessResponse],
    summary="List reusable process library entries",
)
def list_processes(
    process_type: Optional[str] = Query(default=None, description="Filter by process_type"),
    db: Session = Depends(get_db),
):
    return process_service.list_processes(db, process_type=process_type)


@router.post(
    "/processes",
    response_model=ProcessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reusable process in the library",
)
def create_process(payload: ProcessCreate, db: Session = Depends(get_db)):
    return process_service.create_process(db, payload)


@router.get(
    "/processes/{process_id}",
    response_model=ProcessResponse,
    summary="Get a process by ID",
)
def get_process(process_id: str, db: Session = Depends(get_db)):
    return process_service.get_process(db, process_id)


@router.put(
    "/processes/{process_id}",
    response_model=ProcessResponse,
    summary="Update a process",
)
def replace_process(
    process_id: str, payload: ProcessUpdate, db: Session = Depends(get_db)
):
    return process_service.update_process(db, process_id, payload)


@router.patch(
    "/processes/{process_id}/deactivate",
    response_model=ProcessResponse,
    summary="Deactivate a process (soft delete)",
)
def deactivate_process(process_id: str, db: Session = Depends(get_db)):
    return process_service.deactivate_process(db, process_id)
