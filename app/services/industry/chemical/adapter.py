"""Chemical Processing industry adapter — dashboard and lot views over common MES tables."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrder,
    CustomerOrderLine,
    FeasibilityCheck,
    OperationExecution,
    ProductionLot,
    ProductionOrder,
    QualityCheck,
    Resource,
)
from app.schemas.mes_core.schemas import (
    ChemBatchSummaryOut,
    ChemDashboardOut,
    ChemLotLineOut,
    ChemProcessStepOut,
    ChemRawMaterialStatusOut,
    ChemReactorParameterDefinition,
    ChemReactorStatusOut,
)
from app.services.industry.chemical.constants import (
    CHEM_PROCESS_COUNT_KEYS,
    CHEM_PROCESS_FLOW,
    REACTOR_PARAMETER_DEFINITIONS,
)
from app.services.mes_core import dispatch_workflow as mes_core_dispatch
from app.services.mes_core.base import TenantRepository

_TERMINAL_LOT_STATUSES = frozenset({"DISPATCHED", "CLOSED", "CANCELLED"})


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _list_tenant_reactor_resources(db: Session, tenant: TenantContext) -> list[Resource]:
    repo = _repo(db, tenant)
    rows = repo.query(Resource).filter(Resource.resource_type == "MACHINE").all()
    reactors: list[Resource] = []
    for row in rows:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        role = str(meta.get("resource_role") or "").upper()
        code = (row.resource_code or "").upper()
        if role == "REACTOR" or "REACTOR" in code:
            reactors.append(row)
    return reactors


def _latest_feasibility_by_lot(db: Session, tenant: TenantContext) -> dict:
    repo = _repo(db, tenant)
    rows = (
        repo.query(FeasibilityCheck)
        .order_by(FeasibilityCheck.created_at.desc())
        .all()
    )
    latest: dict = {}
    for row in rows:
        lot_id = row.production_lot_id
        if lot_id not in latest:
            latest[lot_id] = row.overall_status
    return latest


def _shop_floor_execution_counts(repo: TenantRepository) -> dict:
    counts: dict = {}
    for row in repo.query(OperationExecution).all():
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        if not (meta.get("is_production_schedule") or meta.get("schedule_code")):
            continue
        lid = row.production_lot_id
        done, total = counts.get(lid, (0, 0))
        total += 1
        if (row.status or "").upper() == "COMPLETED":
            done += 1
        counts[lid] = (done, total)
    return counts


def _lot_pipeline_stage(
    lot_status: Optional[str],
    feasibility_status: Optional[str],
    *,
    exec_done: int = 0,
    exec_total: int = 0,
) -> str:
    st = (lot_status or "").upper()
    if st == "DISPATCHED":
        return "Dispatched"
    if st in ("CLOSED", "CANCELLED"):
        return "Closed"
    if st == "STOCKED":
        return "Finished goods stock"
    if st == "QC_PENDING":
        return "Batch QC"
    if st == "COMPLETED":
        return "Shop-floor complete"
    if st == "IN_PROGRESS":
        if exec_total > 0 and exec_done < exec_total:
            return f"Execution ({exec_done}/{exec_total})"
        if exec_total > 0 and exec_done >= exec_total:
            return "Execution complete"
        feas = (feasibility_status or "").upper()
        if feas in ("READY", "OK", "PASSED"):
            return "Routing / execution"
        return "Reactor charge"
    if st == "CREATED":
        return "Awaiting feasibility"
    return lot_status or "Unknown"


def _lot_line_rows(db: Session, tenant: TenantContext) -> list[ChemLotLineOut]:
    repo = _repo(db, tenant)
    orders = repo.query(CustomerOrder).all()
    line_to_order: dict = {}
    for order in orders:
        for line in repo.query(CustomerOrderLine).filter(
            CustomerOrderLine.order_id == order.customer_order_id
        ).all():
            line_to_order[line.order_line_id] = order.order_code

    po_rows = repo.query(ProductionOrder).all()
    po_by_id = {po.production_order_id: po for po in po_rows}
    feas_by_lot = _latest_feasibility_by_lot(db, tenant)
    exec_counts = _shop_floor_execution_counts(repo)

    lots = (
        repo.query(ProductionLot)
        .order_by(ProductionLot.created_at.desc())
        .all()
    )
    rows: list[ChemLotLineOut] = []
    for lot in lots:
        po = po_by_id.get(lot.production_order_id)
        order_code = line_to_order.get(po.order_line_id) if po else None
        done, total = exec_counts.get(lot.production_lot_id, (0, 0))
        feas = feas_by_lot.get(lot.production_lot_id)
        stage = _lot_pipeline_stage(
            lot.status, feas, exec_done=done, exec_total=total
        )
        in_progress = (lot.status or "").upper() not in _TERMINAL_LOT_STATUSES
        rows.append(
            ChemLotLineOut(
                order_code=order_code,
                production_order_code=po.production_order_code if po else None,
                lot_code=lot.lot_code,
                lot_quantity=lot.lot_quantity,
                status=lot.status,
                feasibility_status=feas,
                pipeline_stage=stage,
                is_in_progress=in_progress,
            )
        )
    return rows


def _reactor_status_rows(db: Session, tenant: TenantContext) -> list[ChemReactorStatusOut]:
    repo = _repo(db, tenant)
    reactor_rows = _list_tenant_reactor_resources(db, tenant)
    executions = (
        repo.query(OperationExecution)
        .order_by(OperationExecution.created_at.desc())
        .all()
    )
    lots_by_id = {lot.production_lot_id: lot for lot in repo.query(ProductionLot).all()}
    rows: list[ChemReactorStatusOut] = []
    for reactor in reactor_rows:
        code = reactor.resource_code
        latest = None
        for ex in executions:
            meta = ex.metadata_ or {}
            if meta.get("reactor_resource_code") == code or meta.get("resource_code") == code:
                latest = ex
                break
        lot = lots_by_id.get(latest.production_lot_id) if latest else None
        if lot is None:
            for candidate in lots_by_id.values():
                if (candidate.status or "").upper() != "IN_PROGRESS":
                    continue
                for ex in executions:
                    if ex.production_lot_id != candidate.production_lot_id:
                        continue
                    meta = ex.metadata_ or {}
                    if meta.get("reactor_resource_code") == code or meta.get("resource_code") == code:
                        lot = candidate
                        latest = ex
                        break
                if lot:
                    break
        status = "IDLE"
        if lot and latest:
            lot_status = (lot.status or "").upper()
            ex_status = (latest.status or "").upper()
            if lot_status == "IN_PROGRESS" and ex_status not in ("COMPLETED", "CLOSED"):
                status = "RUNNING"
            elif lot_status in {"IN_PROGRESS", "COMPLETED", "QC_PENDING"} and ex_status == "COMPLETED":
                status = "COOLING"
        rows.append(
            ChemReactorStatusOut(
                resource_code=code,
                resource_name=reactor.resource_name or code,
                status=status,
                active_lot_code=lot.lot_code if lot else None,
                active_lot_kg=lot.lot_quantity if lot else None,
                last_reading_at=latest.created_at if latest else None,
            )
        )
    return rows


def _raw_material_status(db: Session, tenant: TenantContext) -> ChemRawMaterialStatusOut:
    repo = _repo(db, tenant)
    ordered = Decimal("0")
    charged = Decimal("0")
    open_count = 0
    for order in repo.query(CustomerOrder).all():
        meta = order.metadata_ if isinstance(order.metadata_, dict) else {}
        if meta.get("flow") not in ("RAW_MATERIAL_RECEIPT", "RAW_MATERIAL_INWARD"):
            continue
        open_count += 1
        for line in repo.query(CustomerOrderLine).filter(
            CustomerOrderLine.order_id == order.customer_order_id
        ).all():
            line_meta = line.metadata_ if isinstance(line.metadata_, dict) else {}
            ordered += Decimal(str(line_meta.get("ordered_kg") or line.quantity or 0))
        charged += Decimal(str(meta.get("allocated_to_production_kg") or 0))
    pending = max(Decimal("0"), ordered - charged)
    return ChemRawMaterialStatusOut(
        ordered_kg=ordered,
        charged_kg=charged,
        pending_kg=pending,
        open_order_count=open_count,
    )


def compute_batch_summary(db: Session, tenant: TenantContext) -> ChemBatchSummaryOut:
    repo = _repo(db, tenant)
    lots = repo.query(ProductionLot).all()
    total_qty = sum(Decimal(str(lot.lot_quantity or 0)) for lot in lots)
    planned = sum(
        Decimal(str(po.planned_quantity or 0))
        for po in repo.query(ProductionOrder).all()
    )
    yield_values: list[Decimal] = []
    for lot in lots:
        meta = lot.metadata_ if isinstance(lot.metadata_, dict) else {}
        raw_yield = meta.get("yield_pct") or meta.get("batch_yield_pct")
        if raw_yield is not None:
            try:
                yield_values.append(Decimal(str(raw_yield)))
            except Exception:
                pass
    avg_yield = (
        sum(yield_values) / Decimal(len(yield_values)) if yield_values else None
    )
    return ChemBatchSummaryOut(
        lot_count=len(lots),
        total_planned_quantity=planned,
        total_lot_quantity=total_qty,
        average_yield_pct=avg_yield,
        industry_template_code=tenant.industry_template_code or "CHEMICAL",
    )


def _process_step_rows(db: Session, tenant: TenantContext) -> list[ChemProcessStepOut]:
    repo = _repo(db, tenant)
    exec_counts = _shop_floor_execution_counts(repo)
    inward_count = sum(
        1
        for order in repo.query(CustomerOrder).all()
        if isinstance(order.metadata_, dict)
        and order.metadata_.get("flow") in ("RAW_MATERIAL_RECEIPT", "RAW_MATERIAL_INWARD")
    )
    lot_rows = repo.query(ProductionLot).all()
    reactor_charge_count = sum(
        1 for lot in lot_rows if (lot.status or "").upper() == "IN_PROGRESS"
    )
    routing_lot_count = sum(
        1 for lot in lot_rows if exec_counts.get(lot.production_lot_id, (0, 0))[1] > 0
    )
    stocked_count = sum(
        1 for lot in lot_rows if (lot.status or "").upper() == "STOCKED"
    )
    feasibility_count = repo.query(FeasibilityCheck).count()
    execution_count = sum(
        1
        for ex in repo.query(OperationExecution).all()
        if (ex.metadata_ or {}).get("is_production_schedule")
        or (ex.metadata_ or {}).get("schedule_code")
    )
    reactor_run_count = (
        repo.query(OperationExecution)
        .filter(OperationExecution.metadata_.contains({"process_step": "REACTOR_RUN"}))
        .count()
    )
    blend_count = (
        repo.query(OperationExecution)
        .filter(OperationExecution.metadata_.contains({"process_step": "BLEND"}))
        .count()
    )
    qc_count = (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type != "DISPATCH")
        .count()
    )
    dispatch_count = len(mes_core_dispatch.list_dispatches(db, tenant))
    counts = {
        "CHEM_RAW_MATERIAL_RECEIPT": inward_count,
        "CHEM_RAW_MATERIAL_QC": sum(
            1
            for order in repo.query(CustomerOrder).all()
            if isinstance(order.metadata_, dict)
            and isinstance(order.metadata_.get("raw_material_qc"), dict)
            and order.metadata_["raw_material_qc"].get("qc_status") not in (None, "", "PENDING")
        ),
        "CHEM_REACTOR_CHARGE": reactor_charge_count or routing_lot_count,
        "FEASIBILITY": feasibility_count,
        "EXECUTION": execution_count,
        "ROUTING": routing_lot_count,
        "CHEM_REACTOR_PARAMETERS": reactor_run_count,
        "CHEM_BLEND_FORMULATION": blend_count,
        "CHEM_BATCH_QC": qc_count,
        "CHEM_BATCH_ANALYTICS": len(lot_rows),
        "FG_STOCK": stocked_count,
        "DISPATCH": dispatch_count,
    }
    caps = set(tenant.enabled_capabilities or [])
    steps: list[ChemProcessStepOut] = []
    for step_order, label, path, cap in CHEM_PROCESS_FLOW:
        if cap and cap not in caps:
            continue
        count_key = cap or CHEM_PROCESS_COUNT_KEYS.get(path, "DISPATCH")
        count = counts.get(count_key, 0)
        if count <= 0:
            status = "pending"
        elif count_key == "DISPATCH" and count > 0:
            status = "complete"
        elif count_key in {"FEASIBILITY", "EXECUTION", "ROUTING"} and count > 0:
            status = "done" if count_key in {"FEASIBILITY", "ROUTING"} else "active"
        else:
            status = "active"
        steps.append(
            ChemProcessStepOut(
                step_order=step_order,
                label=label,
                path=path,
                capability_code=cap,
                record_count=count,
                status=status,
            )
        )
    return steps


def list_reactor_parameter_definitions(
    db: Session, tenant: TenantContext
) -> list[ChemReactorParameterDefinition]:
    del db, tenant
    return list(REACTOR_PARAMETER_DEFINITIONS)


def get_dashboard_summary(db: Session, tenant: TenantContext) -> ChemDashboardOut:
    batch_summary = compute_batch_summary(db, tenant)
    raw_material = _raw_material_status(db, tenant)
    reactors = _reactor_status_rows(db, tenant)
    process_steps = _process_step_rows(db, tenant)
    lot_lines = _lot_line_rows(db, tenant)
    repo = _repo(db, tenant)
    qc_count = (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type != "DISPATCH")
        .count()
    )
    dispatch_count = len(mes_core_dispatch.list_dispatches(db, tenant))
    stocked = sum(
        Decimal(str(lot.lot_quantity or 0))
        for lot in repo.query(ProductionLot).all()
        if (lot.status or "").upper() == "STOCKED"
    )
    return ChemDashboardOut(
        batch_summary=batch_summary,
        raw_material=raw_material,
        reactors=reactors,
        process_steps=process_steps,
        lot_lines=lot_lines,
        quality_check_count=qc_count,
        dispatch_count=dispatch_count,
        finished_goods_stock_kg=stocked,
        reactor_parameter_definitions=list_reactor_parameter_definitions(db, tenant),
    )
