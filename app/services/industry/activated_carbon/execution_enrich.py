"""Merge raw-material type execution parameters into lot execution summaries."""

from __future__ import annotations

from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    CustomerOrder,
    CustomerOrderLine,
    Product,
    ProductionLot,
    ProductionOrder,
)
from app.services.industry.activated_carbon import raw_material_types as ac_raw_material_types
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _uuid_or_none(value) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _resolve_raw_material_type(
    db: Session, tenant: TenantContext, lot: ProductionLot
) -> Optional[Any]:
    from app.services.industry.activated_carbon.lot_routing import (
        resolve_raw_material_type_for_lot,
    )

    return resolve_raw_material_type_for_lot(db, tenant, lot)


def _param_from_process_def(defn: dict) -> dict[str, Any]:
    key = (defn.get("key") or defn.get("parameter_code") or "").strip()
    if not key:
        return {}
    code = key
    default = defn.get("default_value")
    data_type = "number"
    object_datatype = defn.get("object_datatype") or ""
    if "string" in object_datatype:
        data_type = "text"
    elif "boolean" in object_datatype:
        data_type = "boolean"
    elif default is not None and str(default).strip():
        try:
            float(str(default))
        except ValueError:
            data_type = "text"
    return {
        "parameter_code": code,
        "parameter_name": defn.get("label") or defn.get("parameter_name") or key,
        "data_type": defn.get("data_type") or data_type,
        "unit": defn.get("unit"),
        "mandatory": bool(defn.get("mandatory") or defn.get("is_mandatory")),
        "default_value": default,
        "display_order": defn.get("display_order"),
        "source": "raw_material_type",
        "subject_uri_template": defn.get("subject_uri_template"),
        "predicate_uri": defn.get("predicate_uri"),
        "object_datatype": defn.get("object_datatype"),
        "ontology_predicate": defn.get("ontology_predicate"),
    }


def _process_step_for_op(op: dict) -> str:
    explicit = (op.get("process_step") or op.get("process_id") or "").upper()
    if explicit:
        return explicit
    code = (op.get("operation_code") or op.get("operation_id") or "").upper()
    if "PYROLYSIS" in code or "CARBON" in code:
        return "PYROLYSIS"
    if "ACTIVATION" in code:
        return "ACTIVATION"
    if "SCREEN" in code:
        return "SCREENING"
    if "QC" in code or "QUALITY" in code:
        return "QC"
    return code.replace("OP-", "", 1)


def _merge_parameters(
    existing: List[dict], extra: List[dict]
) -> List[dict]:
    by_code = {p["parameter_code"]: p for p in existing if p.get("parameter_code")}
    for p in extra:
        code = p.get("parameter_code")
        if code and code not in by_code:
            by_code[code] = p
    return sorted(
        by_code.values(),
        key=lambda x: (x.get("display_order") is None, x.get("display_order") or 999),
    )


def enrich_lot_execution_summary(
    db: Session, tenant: TenantContext, summary: dict[str, Any]
) -> dict[str, Any]:
    lot_code = summary.get("lot_id")
    if not lot_code:
        return summary
    repo = _repo(db, tenant)
    try:
        lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    except Exception:
        return summary

    material_type = _resolve_raw_material_type(db, tenant, lot)
    if not material_type:
        return summary

    exec_params = [
        p
        for p in (material_type.process_parameters or [])
        if (p.get("used_at") or "execution") in ("execution", "both")
    ]
    if not exec_params:
        return summary

    global_defs = [_param_from_process_def(p) for p in exec_params]
    global_defs = [d for d in global_defs if d]

    operations = summary.get("operations") or []
    enriched_ops = []
    for op in operations:
        step = _process_step_for_op(op)
        op_code = (op.get("operation_code") or op.get("operation_id") or "").upper()
        step_defs = []
        for raw in exec_params:
            ps = (raw.get("process_step") or "").upper()
            if ps and ps != step:
                continue
            bound = (raw.get("operation_code") or "").upper()
            if bound and op_code and bound != op_code:
                continue
            if not ps and step not in ("PYROLYSIS", "ACTIVATION", "SCREENING", "QC"):
                continue
            step_defs.append(_param_from_process_def(raw))
        merged = _merge_parameters(list(op.get("parameters") or []), step_defs or global_defs)
        enriched_ops.append({**op, "parameters": merged})
    return {**summary, "operations": enriched_ops}


def enrich_routing_plan_operations(
    db: Session, tenant: TenantContext, lot_code: str, operations: List[dict]
) -> List[dict]:
    """Attach raw-material execution parameters to routing-plan operation rows."""
    repo = _repo(db, tenant)
    try:
        lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    except Exception:
        return operations
    material_type = _resolve_raw_material_type(db, tenant, lot)
    if not material_type:
        return operations
    exec_params = [
        p
        for p in (material_type.process_parameters or [])
        if (p.get("used_at") or "execution") in ("execution", "both")
    ]
    if not exec_params:
        return operations
    global_defs = [_param_from_process_def(p) for p in exec_params]
    global_defs = [d for d in global_defs if d]
    out = []
    for op in operations:
        step = _process_step_for_op(op)
        op_code = (op.get("operation_code") or op.get("operation_id") or "").upper()
        step_defs = []
        for raw in exec_params:
            ps = (raw.get("process_step") or "").upper()
            if ps and ps != step:
                continue
            bound = (raw.get("operation_code") or "").upper()
            if bound and op_code and bound != op_code:
                continue
            if not ps and step not in ("PYROLYSIS", "ACTIVATION", "SCREENING", "QC"):
                continue
            step_defs.append(_param_from_process_def(raw))
        out.append(
            {**op, "parameters": _merge_parameters(op.get("parameters") or [], step_defs or global_defs)}
        )
    return out
