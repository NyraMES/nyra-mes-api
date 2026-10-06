"""Stage ``urn:nyra:predicate:captures`` triples from Masters process_parameters and saved values."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core import (
    OperationExecution,
    ParameterReading,
    ProductionLot,
    RoutingOperation,
    TripleStoreStaging,
)
from app.schemas.mes_core.schemas import TripleCreate
from app.services.industry.activated_carbon.lot_routing import resolve_raw_material_type_for_lot
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.base import TenantRepository

CAPTURE_PREDICATE = "urn:nyra:predicate:captures"
XSD_DECIMAL = "http://www.w3.org/2001/XMLSchema#decimal"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

_SKIP_VALUE_KEYS = frozenset(
    {"status", "completed_at", "process_step", "qc_at", "bag_code", "operation_code"}
)


def parameter_object_uri(key: str) -> str:
    return f"urn:nyra:ac:parameter:{(key or '').strip().upper()}"


def resolve_subject_uri(
    template: Optional[str],
    *,
    order_code: Optional[str] = None,
    lot_code: Optional[str] = None,
) -> str:
    tpl = (template or "urn:nyra:ac:lot:{lot_code}").strip()
    return tpl.format(
        order_code=order_code or "",
        lot_code=lot_code or "",
    )


def _json_val(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _literal_datatype(defn: Optional[dict], value: Any) -> str:
    if defn and defn.get("object_datatype"):
        return str(defn["object_datatype"])
    if isinstance(value, bool):
        return "http://www.w3.org/2001/XMLSchema#boolean"
    if isinstance(value, (int, float, Decimal)):
        return XSD_DECIMAL
    if isinstance(value, str):
        try:
            float(value.strip())
            return XSD_DECIMAL
        except ValueError:
            return XSD_STRING
    return XSD_STRING


def _predicate_for(defn: Optional[dict]) -> str:
    if defn and defn.get("predicate_uri"):
        return str(defn["predicate_uri"])
    if defn and (defn.get("ontology_predicate") or "").strip().lower() == "captures":
        return CAPTURE_PREDICATE
    return CAPTURE_PREDICATE


def _object_uri_for(defn: Optional[dict], field_key: str) -> str:
    if defn and defn.get("object_uri"):
        return str(defn["object_uri"])
    return parameter_object_uri(field_key)


def filter_param_defs(
    param_defs: Iterable[dict],
    *,
    process_step: Optional[str] = None,
    used_at: Optional[str] = None,
    operation_code: Optional[str] = None,
) -> list[dict]:
    step = (process_step or "").strip().upper()
    slot = (used_at or "").strip().lower()
    op_code = (operation_code or "").strip().upper()
    out: list[dict] = []
    for raw in param_defs or []:
        if isinstance(raw, dict):
            defn = raw
        else:
            defn = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        ps = (defn.get("process_step") or "").strip().upper()
        if step and ps and ps != step:
            continue
        ua = (defn.get("used_at") or "execution").strip().lower()
        if slot and ua not in (slot, "both"):
            if not (slot == "inbound" and ua in ("inward", "gate")):
                continue
        bound = (defn.get("operation_code") or "").strip().upper()
        if bound and op_code and bound != op_code:
            continue
        out.append(defn)
    return out


def stage_triple(db: Session, tenant: TenantContext, payload: TripleCreate) -> None:
    """Queue a triple in the current transaction without committing."""
    repo = TenantRepository(db, tenant)
    repo.add(
        TripleStoreStaging(
            subject_uri=payload.subject_uri,
            predicate_uri=payload.predicate_uri,
            object_uri=payload.object_uri,
            object_literal=payload.object_literal,
            object_datatype=payload.object_datatype,
            source_table=payload.source_table,
            source_id=payload.source_id,
            export_status=payload.export_status,
        )
    )


def _write_triple(
    db: Session,
    tenant: TenantContext,
    payload: TripleCreate,
    *,
    flush_only: bool,
) -> None:
    if flush_only:
        stage_triple(db, tenant, payload)
        return
    mes_core_entities.create_triple(db, tenant, payload)


def stage_captures_for_values(
    db: Session,
    tenant: TenantContext,
    *,
    subject_uri: str,
    values: dict[str, Any],
    source_table: str,
    source_id: Optional[UUID],
    param_defs: Optional[list[dict]] = None,
    process_step: Optional[str] = None,
    used_at: Optional[str] = None,
    operation_code: Optional[str] = None,
    only_masters_keys: bool = False,
    flush_only: bool = False,
) -> int:
    """Write capture triples for non-null values. Returns number of literal triples staged."""
    if not subject_uri or not values:
        return 0

    defs_by_key = {}
    filtered = filter_param_defs(
        param_defs or [],
        process_step=process_step,
        used_at=used_at,
        operation_code=operation_code,
    )
    for defn in filtered:
        key = (defn.get("key") or "").strip()
        if key:
            defs_by_key[key] = defn

    staged_keys: set[str] = set()
    count = 0

    for key, defn in defs_by_key.items():
        if key in staged_keys or key in _SKIP_VALUE_KEYS:
            continue
        value = values.get(key)
        if value is None:
            continue
        _write_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject_uri,
                predicate_uri=_predicate_for(defn),
                object_uri=_object_uri_for(defn, key),
                object_literal=str(_json_val(value)),
                object_datatype=_literal_datatype(defn, value),
                source_table=source_table,
                source_id=source_id,
            ),
            flush_only=flush_only,
        )
        staged_keys.add(key)
        count += 1

    if only_masters_keys and not defs_by_key:
        return count

    if only_masters_keys:
        return count

    for field, value in values.items():
        if value is None or field in staged_keys or field in _SKIP_VALUE_KEYS:
            continue
        _write_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject_uri,
                predicate_uri=CAPTURE_PREDICATE,
                object_uri=parameter_object_uri(field),
                object_literal=str(_json_val(value)),
                object_datatype=_literal_datatype(None, value),
                source_table=source_table,
                source_id=source_id,
            ),
            flush_only=flush_only,
        )
        count += 1

    return count


def stage_inbound_step_captures(
    db: Session,
    tenant: TenantContext,
    order,
    process_step: str,
    values: dict[str, Any],
    material_type,
    *,
    operation_code: Optional[str] = None,
) -> int:
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    param_defs = list(material_type.process_parameters or [])
    return stage_captures_for_values(
        db,
        tenant,
        subject_uri=subject,
        values=values,
        source_table="trn.customer_order",
        source_id=order.customer_order_id,
        param_defs=param_defs,
        process_step=process_step,
        used_at="inbound",
        operation_code=operation_code,
    )


def stage_inward_receipt_captures(
    db: Session,
    tenant: TenantContext,
    order,
    material_type,
    receipt: dict[str, Any],
    *,
    received_qty_kg: Optional[Decimal] = None,
) -> int:
    values = dict(receipt or {})
    if received_qty_kg is not None:
        values["received_qty_kg"] = received_qty_kg
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    param_defs = list(material_type.process_parameters or [])
    return stage_captures_for_values(
        db,
        tenant,
        subject_uri=subject,
        values=values,
        source_table="trn.customer_order",
        source_id=order.customer_order_id,
        param_defs=param_defs,
        process_step="RAW_MATERIAL_INWARD",
        used_at="inward",
        only_masters_keys=True,
    )


def _readings_to_values(readings: list[ParameterReading]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in readings:
        code = (row.parameter_code or "").strip()
        if not code:
            continue
        if row.reading_value is not None:
            out[code] = row.reading_value
        elif row.reading_text is not None:
            out[code] = row.reading_text
    return out


def stage_execution_parameter_triples(
    db: Session,
    tenant: TenantContext,
    execution_code: str,
) -> int:
    repo = TenantRepository(db, tenant)
    try:
        row = repo.get_by_code(
            OperationExecution, OperationExecution.execution_code, execution_code
        )
    except Exception:
        return 0

    readings = (
        repo.query(ParameterReading)
        .filter(ParameterReading.execution_id == row.execution_id)
        .order_by(ParameterReading.recorded_at.asc())
        .all()
    )
    if not readings:
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        embedded = meta.get("parameter_readings") or meta.get("captured_parameters")
        if isinstance(embedded, dict):
            values = embedded
        else:
            return 0
    else:
        values = _readings_to_values(readings)

    if not values:
        return 0

    lot = repo.get_by_pk(
        ProductionLot, ProductionLot.production_lot_id, row.production_lot_id
    )
    material_type = resolve_raw_material_type_for_lot(db, tenant, lot)
    if not material_type:
        return 0

    rop = repo.get_by_pk(
        RoutingOperation,
        RoutingOperation.routing_operation_id,
        row.routing_operation_id,
    )
    process_step = (rop.process_code or rop.process_type or "").upper()
    operation_code = rop.operation_code or ""

    param_defs = list(material_type.process_parameters or [])
    subject_tpl = "urn:nyra:ac:lot:{lot_code}"
    for defn in filter_param_defs(
        param_defs,
        process_step=process_step,
        used_at="execution",
        operation_code=operation_code,
    ):
        tpl = defn.get("subject_uri_template")
        if tpl:
            subject_tpl = tpl
            break

    subject_uri = resolve_subject_uri(
        subject_tpl,
        lot_code=lot.lot_code,
    )

    return stage_captures_for_values(
        db,
        tenant,
        subject_uri=subject_uri,
        values=values,
        source_table="exec.operation_execution",
        source_id=row.execution_id,
        param_defs=param_defs,
        process_step=process_step,
        used_at="execution",
        operation_code=operation_code,
    )
