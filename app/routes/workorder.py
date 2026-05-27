"""Work-order routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.schedule import (
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderHoldRequest,
    WorkOrderOut,
    WorkOrderStartRequest,
)
from app.services import workorder_service

router = APIRouter(tags=[Tags.WORK_ORDER])


@router.post(
    "/work-order",
    response_model=WorkOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a work order against a lot+operation (defaults to Released)",
)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db)):
    return workorder_service.create_work_order(db, payload)


@router.get(
    "/work-orders",
    response_model=List[WorkOrderOut],
    summary="List work orders",
)
def list_work_orders(db: Session = Depends(get_db)):
    return workorder_service.list_work_orders(db)


@router.get(
    "/work-order/{work_order_id}",
    response_model=WorkOrderOut,
    summary="Get a work order by ID",
)
def get_work_order(work_order_id: str, db: Session = Depends(get_db)):
    return workorder_service.get_work_order(db, work_order_id)


@router.put(
    "/work-order/{work_order_id}/start",
    response_model=WorkOrderOut,
    summary="Mark a Released work order as InProgress (shop-floor start)",
)
def start_work_order(
    work_order_id: str,
    payload: WorkOrderStartRequest = WorkOrderStartRequest(),
    db: Session = Depends(get_db),
):
    return workorder_service.start_work_order(db, work_order_id, payload)


@router.put(
    "/work-order/{work_order_id}/hold",
    response_model=WorkOrderOut,
    summary="Put a work order on hold (material missing, machine down, etc.)",
)
def hold_work_order(
    work_order_id: str,
    payload: WorkOrderHoldRequest,
    db: Session = Depends(get_db),
):
    return workorder_service.hold_work_order(db, work_order_id, payload)


@router.put(
    "/work-order/{work_order_id}/resume",
    response_model=WorkOrderOut,
    summary="Resume a work order that was on hold",
)
def resume_work_order(work_order_id: str, db: Session = Depends(get_db)):
    return workorder_service.resume_work_order(db, work_order_id)


@router.put(
    "/work-order/{work_order_id}/complete",
    response_model=WorkOrderOut,
    summary="Complete an InProgress work order",
)
def complete_work_order(
    work_order_id: str,
    payload: WorkOrderCompleteRequest,
    db: Session = Depends(get_db),
):
    return workorder_service.complete_work_order(db, work_order_id, payload)


@router.get(
    "/lot/{lot_id}/execution-summary",
    summary="Aggregate work-order state for a lot (used by the execution screen)",
)
def lot_execution_summary(
    lot_id: str,
    sync: bool = False,
    db: Session = Depends(get_db),
):
    """``sync=false`` skips schedule→WO materialisation (faster refresh after actions)."""
    return workorder_service.lot_execution_summary(db, lot_id, sync=sync)
