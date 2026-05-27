"""Dashboard cross-domain KPI routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.models.dispatch import Dispatch
from app.models.oee import OEEDailySummary
from app.models.production import ProductionOrder
from app.models.quality import NCR
from app.models.work_order import WorkOrder
from app.services import oee_service, resolver

router = APIRouter(prefix="/dashboard", tags=[Tags.DASHBOARD])


@router.get("/kpis", summary="Cross-domain KPI tile data")
def get_dashboard_kpis(db: Session = Depends(get_db)):
    production_orders = db.query(ProductionOrder).count()
    work_orders = db.query(WorkOrder).count()
    ncr_count = db.query(NCR).count()
    open_ncrs = (
        db.query(NCR).filter((NCR.status.is_(None)) | (NCR.status != "Closed")).count()
    )
    dispatch_count = db.query(Dispatch).count()
    avg_oee = db.query(func.avg(OEEDailySummary.oee_percent)).scalar()
    return {
        "production_orders": production_orders,
        "work_orders": work_orders,
        "ncr_count": ncr_count,
        "open_ncrs": open_ncrs,
        "dispatch_count": dispatch_count,
        "average_oee": round(float(avg_oee or 0), 2),
    }


@router.get("/oee-trend", summary="Daily OEE trend (plant average per day)")
def get_oee_trend(db: Session = Depends(get_db)):
    return oee_service.build_trend_by_day(oee_service.list_oee_summaries(db))


@router.get("/open-work-orders", summary="Latest 10 open work orders")
def get_open_work_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(WorkOrder)
        .filter(
            (WorkOrder.work_order_status.is_(None))
            | (WorkOrder.work_order_status != "Completed")
        )
        .order_by(WorkOrder.id.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "work_order_id": r.work_order_code,
            "lot_id": resolver.lot_code(db, r.lot_id) if r.lot_id else None,
            "operation_id": (
                resolver.operation_code(db, r.routing_operation_id)
                if r.routing_operation_id
                else None
            ),
            "work_order_status": r.work_order_status,
            "released_at": r.released_at,
            "started_at": r.started_at,
        }
        for r in rows
    ]


@router.get("/open-ncrs", summary="Latest 10 open NCRs")
def get_open_ncrs(db: Session = Depends(get_db)):
    rows = (
        db.query(NCR)
        .filter((NCR.status.is_(None)) | (NCR.status != "Closed"))
        .order_by(NCR.id.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "ncr_id": r.ncr_code,
            "disposition": r.disposition,
            "status": r.status,
            "rejected_quantity": r.rejected_quantity,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/recent-dispatches", summary="Latest 10 dispatches")
def get_recent_dispatches(db: Session = Depends(get_db)):
    rows = (
        db.query(Dispatch)
        .order_by(Dispatch.dispatch_date.desc().nullslast(), Dispatch.id.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "dispatch_id": r.dispatch_code,
            "customer_id": resolver.customer_code(db, r.customer_id) if r.customer_id else None,
            "order_id": resolver.order_code(db, r.order_id) if r.order_id else None,
            "dispatch_date": r.dispatch_date,
            "vehicle_number": r.vehicle_number,
            "dispatch_status": r.dispatch_status,
        }
        for r in rows
    ]
