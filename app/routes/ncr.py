"""Non-Conformance Report routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.quality import NCRCreate, NCROut
from app.services import ncr_service

router = APIRouter(tags=[Tags.NCR])


@router.post(
    "/ncr",
    response_model=NCROut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an NCR (typically against a failed inspection result)",
)
def create_ncr(payload: NCRCreate, db: Session = Depends(get_db)):
    return ncr_service.create_ncr(db, payload)


@router.get(
    "/ncrs",
    response_model=List[NCROut],
    summary="List NCRs",
)
def list_ncrs(db: Session = Depends(get_db)):
    return ncr_service.list_ncrs(db)
