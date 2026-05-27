"""Feasibility intelligence routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.feasibility import FeasibilityResponse
from app.services import feasibility_service

router = APIRouter(tags=[Tags.FEASIBILITY, Tags.INTELLIGENCE])


@router.get(
    "/feasibility/{lot_id}",
    response_model=FeasibilityResponse,
    summary=(
        "Return material / machine / tool / workforce / overall feasibility "
        "for a lot, plus the blocking reasons. The verdict is persisted to "
        "``trn.feasibility_gate`` for downstream gating."
    ),
)
def get_feasibility(lot_id: str, db: Session = Depends(get_db)):
    return feasibility_service.check_feasibility(db, lot_id)


@router.post(
    "/feasibility/{lot_id}/recheck",
    response_model=FeasibilityResponse,
    summary="Force a fresh feasibility check for a lot (overwrites the stored gate)",
)
def recheck_feasibility(lot_id: str, db: Session = Depends(get_db)):
    return feasibility_service.check_feasibility(db, lot_id)
