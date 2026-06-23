"""Activated Carbon lot routing — mes_core routing plan + work-order materialisation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    OperationExecution,
    ProductionLot,
    RoutingOperation,
    RoutingOperationParameter,
)
from app.services.industry.activated_carbon.routing_helpers import _is_schedule_row
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.feasibility import is_ready_for_scheduling, run_feasibility_check
from app.services.mes_core.ids import resolve_business_code
from app.services.industry.activated_carbon.execution_enrich import (
    enrich_routing_plan_operations,
)
from app.services.mes_core.routing_helpers import load_lot_routing

_SCHEDULE_META_FLAG = "is_production_schedule"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parameters_for_operation(repo: TenantRepository, routing_operation_id) -> list:
    rows = (
        repo.query(RoutingOperationParameter)
        .filter(
            RoutingOperationParameter.routing_operation_id == routing_operation_id,
            RoutingOperationParameter.is_active.is_(True),
        )
        .order_by(RoutingOperationParameter.display_order.nulls_last())
        .all()
    )
    return [
        {
            "parameter_code": p.parameter_code,
            "parameter_name": p.parameter_name,
            "data_type": p.data_type or "text",
            "unit": p.unit,
            "min_value": float(p.min_value) if p.min_value is not None else None,
            "max_value": float(p.max_value) if p.max_value is not None else None,
            "mandatory": bool(p.is_mandatory),
            "display_order": p.display_order,
        }
        for p in rows
        if p.parameter_code
    ]


def get_lot_routing_plan(db: Session, tenant: TenantContext, lot_code: str) -> dict[str, Any]:
    """Routing plan shape compatible with the workflow RoutingFlow UI."""
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    product, routing, operations, _qty = load_lot_routing(repo, lot)

    if not product:
        raise WorkflowError(f"Lot '{lot_code}': cannot resolve product")
    if not routing:
        raise WorkflowError(
            f"No active routing defined for product {product.product_code}",
            details={"hint": "Run seed with --install-master or define RT-AC routing in master data"},
        )
    if not operations:
        raise WorkflowError(f"Routing '{routing.routing_code}' has no operations")

    existing_rows = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot.production_lot_id)
        .all()
    )
    wo_by_op: dict = {}
    for ex in existing_rows:
        rid = ex.routing_operation_id
        if rid not in wo_by_op:
            wo_by_op[rid] = ex
            continue
        if _is_schedule_row(ex) and not _is_schedule_row(wo_by_op[rid]):
            wo_by_op[rid] = ex

    plan_ops = []
    generated_count = 0
    for op in operations:
        wo = wo_by_op.get(op.routing_operation_id)
        if wo:
            generated_count += 1
        meta = op.metadata_ if isinstance(op.metadata_, dict) else {}
        process_step = meta.get("process_step")
        ui_status = None
        if wo:
            status = (wo.status or "").strip().upper()
            if status == "NOT_STARTED":
                ui_status = "Ready"
            elif status == "IN_PROGRESS":
                ui_status = "In Progress"
            elif status == "COMPLETED":
                ui_status = "Completed"
            else:
                ui_status = wo.status or "Pending"

        plan_ops.append(
            {
                "operation_id": op.operation_code,
                "operation_code": op.operation_code,
                "operation_sequence": op.operation_sequence,
                "operation_name": op.operation_name,
                "process_id": process_step,
                "process_name": process_step.replace("_", " ").title() if process_step else None,
                "is_mandatory": meta.get("is_mandatory", True),
                "work_order_id": wo.execution_code if wo else None,
                "work_order_generated": wo is not None,
                "status": ui_status or ("Pending" if not wo else "Ready"),
                "parameters": _parameters_for_operation(repo, op.routing_operation_id),
            }
        )

    pending_count = len(plan_ops) - generated_count
    plan_ops = enrich_routing_plan_operations(db, tenant, lot_code, plan_ops)
    return {
        "lot_id": lot_code,
        "part_id": product.product_code,
        "part_name": product.product_name,
        "routing_id": routing.routing_code,
        "routing_version": routing.routing_version,
        "operations": plan_ops,
        "total_operations": len(plan_ops),
        "generated_work_orders": generated_count,
        "pending_work_orders": pending_count,
        "can_generate": pending_count > 0,
        "routing_complete": pending_count == 0 and len(plan_ops) > 0,
    }


def generate_lot_route(db: Session, tenant: TenantContext, lot_code: str) -> dict[str, Any]:
    """Materialise routing operations as shop-floor work orders (mes_core executions)."""
    if not is_ready_for_scheduling(db, tenant, lot_code):
        raise WorkflowError(
            "Lot is not feasibility-ready — run Feasibility Gate for this lot first",
            details={"lot_id": lot_code},
        )
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    _product, routing, operations, _qty = load_lot_routing(repo, lot)
    if not routing or not operations:
        raise WorkflowError(f"No routing operations to generate for lot '{lot_code}'")

    existing = (
        repo.query(OperationExecution)
        .filter(OperationExecution.production_lot_id == lot.production_lot_id)
        .all()
    )
    # Include kiln-feed / process captures — not only schedule-flagged rows — so we do
    # not insert a second execution for the same routing_operation_id (e.g. ACTIVATION).
    by_op: dict = {}
    for ex in existing:
        rid = ex.routing_operation_id
        if rid not in by_op:
            by_op[rid] = ex
            continue
        if _is_schedule_row(ex) and not _is_schedule_row(by_op[rid]):
            by_op[rid] = ex

    created = []
    for op in operations:
        if op.routing_operation_id in by_op:
            continue
        op_meta = op.metadata_ if isinstance(op.metadata_, dict) else {}
        execution_code = resolve_business_code(db, provided=None, entity="operation_execution")
        row = repo.add(
            OperationExecution(
                execution_code=execution_code,
                production_lot_id=lot.production_lot_id,
                routing_operation_id=op.routing_operation_id,
                status="NOT_STARTED",
                metadata_={
                    _SCHEDULE_META_FLAG: True,
                    "schedule_code": execution_code,
                    "schedule_status": "Scheduled",
                    "released_at": _utcnow_iso(),
                    "source": "ac_routing_generate",
                    "process_step": op_meta.get("process_step"),
                    "is_mandatory": op_meta.get("is_mandatory", True),
                    "industry_template_code": tenant.industry_template_code,
                },
            )
        )
        created.append(
            {
                "work_order_id": row.execution_code,
                "operation_sequence": op.operation_sequence,
                "operation_code": op.operation_code,
                "operation_name": op.operation_name,
                "status": "Released",
            }
        )

    try:
        repo.db.commit()
    except Exception as exc:
        repo.db.rollback()
        detail = str(getattr(getattr(exc, "orig", None), "pgerror", None) or exc)
        raise WorkflowError(
            f"Could not save work orders for lot '{lot_code}'",
            details={"error": detail},
        ) from exc
    feasibility = run_feasibility_check(db, tenant, lot_code)
    return {
        "message": "Route generated for lot",
        "lot_id": lot_code,
        "operation_count": len(created),
        "operations": created,
        "feasibility": feasibility.model_dump(),
    }
