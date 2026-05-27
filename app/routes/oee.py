"""OEE intelligence routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.oee import (
    OEEDailySummaryCreate,
    OEEDailySummaryOut,
    OEEIntelligenceResponse,
    OEEMachineSummary,
)
from app.services import oee_service

router = APIRouter(tags=[Tags.OEE, Tags.INTELLIGENCE])


@router.get(
    "/oee/intelligence",
    response_model=OEEIntelligenceResponse,
    summary="Plant OEE KPIs, trend, machine ranking, and downtime hotspots",
)
def get_oee_intelligence(db: Session = Depends(get_db)):
    return oee_service.get_oee_intelligence(db)


@router.get(
    "/machine/oee/{machine_id}",
    response_model=OEEMachineSummary,
    summary=(
        "Compute Availability, Performance, Quality and OEE for a machine "
        "(averaged over the last N days; default 30)"
    ),
)
def get_machine_oee(
    machine_id: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return oee_service.machine_oee_summary(db, machine_id, days=days)


@router.get(
    "/oee-daily-summary",
    response_model=List[OEEDailySummaryOut],
    summary="List OEE daily summary rows",
)
def list_oee_daily_summaries(db: Session = Depends(get_db)):
    return oee_service.list_oee_summaries(db)


@router.post(
    "/oee-daily-summary",
    response_model=OEEDailySummaryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a daily OEE row for a machine",
)
def create_oee_daily_summary(
    payload: OEEDailySummaryCreate, db: Session = Depends(get_db)
):
    return oee_service.create_oee_summary(db, payload)
