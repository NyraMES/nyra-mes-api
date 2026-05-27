"""Dispatch routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.dispatch import (
    DispatchCreate,
    DispatchLineCreate,
    DispatchLineOut,
    DispatchOut,
)
from app.services import dispatch_service

router = APIRouter(tags=[Tags.DISPATCH])


@router.post(
    "/dispatch",
    response_model=DispatchOut,
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Create a dispatch. Each lot must have all operations complete, "
        "at least one passing inspection, and no open NCR."
    ),
)
def create_dispatch(payload: DispatchCreate, db: Session = Depends(get_db)):
    dispatch, _lines = dispatch_service.create_dispatch(db, payload)
    return dispatch


@router.post(
    "/dispatch/{dispatch_id}/line",
    response_model=DispatchLineOut,
    status_code=status.HTTP_201_CREATED,
    summary="Append a line to an existing dispatch (same gate applies)",
)
def add_dispatch_line(
    dispatch_id: str,
    payload: DispatchLineCreate,
    db: Session = Depends(get_db),
):
    return dispatch_service.add_dispatch_line(db, dispatch_id, payload)


@router.get(
    "/dispatches",
    response_model=List[DispatchOut],
    summary="List dispatches (newest first)",
)
def list_dispatches(db: Session = Depends(get_db)):
    return dispatch_service.list_dispatches(db)


@router.get(
    "/dispatch/{dispatch_id}",
    response_model=DispatchOut,
    summary="Get a dispatch by ID",
)
def get_dispatch(dispatch_id: str, db: Session = Depends(get_db)):
    return dispatch_service.get_dispatch(db, dispatch_id)


@router.get(
    "/dispatch/{dispatch_id}/lines",
    response_model=List[DispatchLineOut],
    summary="List lines of a dispatch",
)
def list_lines(dispatch_id: str, db: Session = Depends(get_db)):
    return dispatch_service.list_lines(db, dispatch_id)
