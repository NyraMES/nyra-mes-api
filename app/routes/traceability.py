"""Traceability intelligence routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.traceability import TraceabilityResponse
from app.services import traceability_service

router = APIRouter(tags=[Tags.TRACEABILITY, Tags.INTELLIGENCE])


@router.get(
    "/traceability/{lot_id}",
    response_model=TraceabilityResponse,
    summary=(
        "Full end-to-end traceability graph for a lot: Customer -> Order -> "
        "Production Order -> Lot -> Dispatch (with ontology edges for "
        "RDF / SPARQL export)."
    ),
)
def get_lot_traceability(lot_id: str, db: Session = Depends(get_db)):
    return traceability_service.get_traceability(db, lot_id)
