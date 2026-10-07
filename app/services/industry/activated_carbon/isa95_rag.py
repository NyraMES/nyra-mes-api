"""ISA-95 utilization RAG bands for machine monthly output vs designed capacity.

Plant-level Masters config (tenant metadata). This is not shop-floor capture and
does not add inward/lot triplet subjects.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import Tenant

META_KEY = "ac_isa95_utilization_rag"

# Align with AC_ISA95_KPI_ONTOLOGY.thresholds (green 90 / amber 70 / red < 70).
DEFAULT_GREEN_MIN_PCT = 90
DEFAULT_AMBER_MIN_PCT = 70
DEFAULT_RED_BELOW_PCT = 70


def default_utilization_rag() -> dict[str, int]:
    return {
        "green_min_pct": DEFAULT_GREEN_MIN_PCT,
        "amber_min_pct": DEFAULT_AMBER_MIN_PCT,
        "red_below_pct": DEFAULT_RED_BELOW_PCT,
    }


def _tenant_row(db: Session, tenant: TenantContext) -> Tenant:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        row = db.query(Tenant).filter(Tenant.tenant_id == tenant.tenant_id).first()
    if row is None:
        raise ValueError(f"Tenant '{tenant.tenant_code}' not found")
    return row


def _clamp_pct(raw: Any, fallback: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return max(0, min(100, value))


def normalize_utilization_rag(payload: dict | None) -> dict[str, int]:
    data = payload if isinstance(payload, dict) else {}
    green = _clamp_pct(data.get("green_min_pct"), DEFAULT_GREEN_MIN_PCT)
    amber = _clamp_pct(data.get("amber_min_pct"), DEFAULT_AMBER_MIN_PCT)
    red_raw = data.get("red_below_pct")
    red_below = amber if red_raw in (None, "") else _clamp_pct(red_raw, amber)
    if green < 1:
        green = DEFAULT_GREEN_MIN_PCT
    if amber > green:
        raise ValidationError("Amber % must be less than Green %.")
    if red_below > amber:
        raise ValidationError("Red-below % cannot be higher than Amber %.")
    return {
        "green_min_pct": green,
        "amber_min_pct": amber,
        "red_below_pct": red_below,
    }


def get_utilization_rag(db: Session, tenant: TenantContext) -> dict[str, int]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(META_KEY)
    if not isinstance(block, dict):
        return default_utilization_rag()
    try:
        return normalize_utilization_rag(block)
    except ValidationError:
        return default_utilization_rag()


def save_utilization_rag(db: Session, tenant: TenantContext, payload: dict) -> dict[str, int]:
    cleaned = normalize_utilization_rag(payload)
    row = _tenant_row(db, tenant)
    meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
    meta[META_KEY] = cleaned
    row.metadata_ = meta
    flag_modified(row, "metadata_")
    db.commit()
    db.refresh(row)
    return cleaned
