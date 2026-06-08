"""Operational intelligence hub aggregates for nyra_mes_core."""

from __future__ import annotations

from typing import Any, List

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import OperationExecution, ProductionLot, RoutingOperation
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.dispatch_workflow import list_dispatches
from app.services.mes_core.oee_intelligence import hub_oee_bundle
from app.services.mes_core.entities import (
    list_customer_orders,
    list_production_lots,
    list_production_orders,
)
from app.services.mes_core.execution_workflow import _is_schedule_row, _meta, _ui_status
from app.services.mes_core.quality_workflow import list_ncrs


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _lot_code_map(db: Session, tenant: TenantContext) -> dict[Any, str]:
    rows = _repo(db, tenant).query(ProductionLot).all()
    return {row.production_lot_id: row.lot_code for row in rows}


def _operation_code_map(db: Session, tenant: TenantContext) -> dict[Any, str]:
    rows = _repo(db, tenant).query(RoutingOperation).all()
    return {row.routing_operation_id: row.operation_code for row in rows}


def _open_work_orders(
    db: Session, tenant: TenantContext, *, limit: int = 10
) -> List[dict[str, Any]]:
    lot_codes = _lot_code_map(db, tenant)
    op_codes = _operation_code_map(db, tenant)
    rows = (
        _repo(db, tenant)
        .query(OperationExecution)
        .order_by(OperationExecution.created_at.desc())
        .all()
    )
    open_rows = [
        row
        for row in rows
        if _is_schedule_row(row) and (row.status or "").upper() != "COMPLETED"
    ][:limit]
    result = []
    for row in open_rows:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        result.append(
            {
                "work_order_id": row.execution_code,
                "lot_id": lot_codes.get(row.production_lot_id),
                "operation_id": op_codes.get(row.routing_operation_id),
                "work_order_status": _ui_status(row.status),
                "released_at": meta.get("released_at"),
                "started_at": row.started_at.isoformat() if row.started_at else None,
            }
        )
    return result


def get_intelligence_hub(db: Session, tenant: TenantContext) -> dict[str, Any]:
    repo = _repo(db, tenant)
    orders = list_customer_orders(db, tenant)
    lots = list_production_lots(db, tenant)
    production_orders = list_production_orders(db, tenant)
    ncrs = list_ncrs(db, tenant)
    dispatches = list_dispatches(db, tenant)

    schedule_rows = [
        row
        for row in repo.query(OperationExecution).all()
        if _is_schedule_row(row)
    ]
    open_ncrs = [
        n
        for n in ncrs
        if (n.status or "").upper() not in ("CLOSED", "RESOLVED")
    ]

    open_work_orders = _open_work_orders(db, tenant)
    oee_trend, oee_summaries, average_oee = hub_oee_bundle(db, tenant)
    from app.services.mes_core.oee_intelligence import get_oee_intelligence

    oee_intel = get_oee_intelligence(db, tenant)
    plant_kpis = {
        "availability": float(oee_intel.plant.availability or 0),
        "performance": float(oee_intel.plant.performance or 0),
        "quality": float(oee_intel.plant.quality or 0),
        "oee": float(oee_intel.plant.oee or 0),
    }

    line_to_order: dict[Any, str] = {}
    for order in orders:
        for line in order.lines:
            line_to_order[line.order_line_id] = order.order_code

    po_by_code = {
        po.production_order_code: po for po in production_orders if po.production_order_code
    }

    order_lot_lines = []
    for lot in lots:
        po = po_by_code.get(lot.production_order_code or "")
        order_code = line_to_order.get(po.order_line_id) if po else None
        order_lot_lines.append(
            {
                "order_id": order_code,
                "production_order_id": lot.production_order_code,
                "lot_id": lot.lot_code,
                "lot_quantity": float(lot.lot_quantity),
                "status": lot.status,
            }
        )

    return {
        "kpis": {
            "production_orders": len(production_orders),
            "work_orders": len(schedule_rows),
            "ncr_count": len(ncrs),
            "open_ncrs": len(open_ncrs),
            "dispatch_count": len(dispatches),
            "average_oee": average_oee,
        },
        "orders": [
            {
                "order_id": order.order_code,
                "customer_id": order.customer_code or str(order.customer_id),
                "status": order.status,
                "delivery_date": (
                    order.delivery_date.isoformat() if order.delivery_date else None
                ),
            }
            for order in orders
        ],
        "lots": [
            {
                "lot_id": lot.lot_code,
                "production_order_id": lot.production_order_code,
                "lot_quantity": float(lot.lot_quantity),
                "status": lot.status,
            }
            for lot in lots
        ],
        "order_lot_lines": order_lot_lines,
        "oee_trend": oee_trend,
        "oee_summaries": oee_summaries,
        "plant_kpis": plant_kpis,
        "open_work_orders": open_work_orders,
        "open_ncrs": [
            {
                "ncr_id": n.ncr_id,
                "disposition": n.disposition,
                "status": n.status,
                "rejected_quantity": (
                    float(n.rejected_quantity) if n.rejected_quantity is not None else None
                ),
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in open_ncrs[:10]
        ],
        "dispatches": [
            {
                "dispatch_id": d.dispatch_id,
                "customer_id": d.customer_id,
                "order_id": d.order_id,
                "dispatch_date": d.dispatch_date.isoformat() if d.dispatch_date else None,
                "vehicle_number": d.vehicle_number,
                "dispatch_status": d.dispatch_status,
            }
            for d in dispatches[:10]
        ],
    }
