"""Tenant-level inbound catalogs — rotaries and RM outward splits (admin)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import Tenant

ADMIN_META_KEY = "ac_inbound_admin"

DEFAULT_ROTARIES = (
    {"code": "ROTARY_A", "name": "Rotary A"},
    {"code": "ROTARY_B", "name": "Rotary B"},
)

DEFAULT_OUTWARD_SPLITS = (
    {"key": "minus20_1st", "label": "-20 1st Stage"},
    {"key": "grade_1st", "label": "Grade 1st Stage"},
    {"key": "unburnt", "label": "Unburnt"},
    {"key": "stones", "label": "Stones"},
)

OUTWARD_GRADE_LABELS = tuple(row["label"] for row in DEFAULT_OUTWARD_SPLITS)
OUTWARD_BYPRODUCT_GRADES = frozenset({"Unburnt", "Stones"})


def default_inbound_admin() -> dict[str, Any]:
    return {
        "rotaries": [dict(row) for row in DEFAULT_ROTARIES],
        "outward_splits": [dict(row) for row in DEFAULT_OUTWARD_SPLITS],
    }


def _tenant_row(db: Session, tenant: TenantContext) -> Tenant:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        row = db.query(Tenant).filter(Tenant.tenant_id == tenant.tenant_id).first()
    if row is None:
        raise ValueError(f"Tenant '{tenant.tenant_code}' not found")
    return row


def _normalize_rotaries(rows) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("code") or "").strip()
        code = str(raw.get("code") or name).strip().upper().replace(" ", "_")
        if not name or code in seen:
            continue
        seen.add(code)
        out.append({"code": code, "name": name})
    return out or [dict(row) for row in DEFAULT_ROTARIES]


def _normalize_splits(rows) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows or []):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("name") or "").strip()
        key = str(raw.get("key") or f"split_{index + 1}").strip().lower().replace(" ", "_")
        if not label or key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "label": label})
    return out or [dict(row) for row in DEFAULT_OUTWARD_SPLITS]


def get_inbound_admin(db: Session, tenant: TenantContext) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(ADMIN_META_KEY)
    if not isinstance(block, dict):
        return default_inbound_admin()
    return {
        "rotaries": _normalize_rotaries(block.get("rotaries")),
        "outward_splits": _normalize_splits(block.get("outward_splits")),
    }


def save_inbound_admin(db: Session, tenant: TenantContext, payload: dict) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
    cleaned = {
        "rotaries": _normalize_rotaries(payload.get("rotaries")),
        "outward_splits": _normalize_splits(payload.get("outward_splits")),
    }
    meta[ADMIN_META_KEY] = cleaned
    row.metadata_ = meta
    flag_modified(row, "metadata_")
    db.commit()
    db.refresh(row)
    return cleaned


def ensure_default_inbound_admin(db: Session, tenant: TenantContext) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    if isinstance(meta.get(ADMIN_META_KEY), dict) and meta[ADMIN_META_KEY].get("rotaries"):
        return get_inbound_admin(db, tenant)
    return save_inbound_admin(db, tenant, default_inbound_admin())


def rotary_names(db: Session, tenant: TenantContext) -> tuple[str, ...]:
    return tuple(row["name"] for row in get_inbound_admin(db, tenant)["rotaries"])


def outward_split_labels(db: Session, tenant: TenantContext) -> tuple[str, ...]:
    return tuple(row["label"] for row in get_inbound_admin(db, tenant)["outward_splits"])


def outward_grade_labels(db: Session, tenant: TenantContext) -> tuple[str, ...]:
    labels = [row["label"] for row in get_inbound_admin(db, tenant)["outward_splits"]]
    cleaned = [_canonical_outward_grade(label) for label in labels]
    seen: list[str] = []
    for label in cleaned:
        if label and label not in seen:
            seen.append(label)
    return tuple(seen) or OUTWARD_GRADE_LABELS


def _canonical_outward_grade(label: str) -> str:
    raw = str(label or "").strip()
    lower = raw.lower()
    for suffix in (" - rotary a", " - rotary b"):
        if lower.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
            lower = raw.lower()
            break
    aliases = {
        "-20 1st stage": "-20 1st Stage",
        "-20 2nd stage": "-20 1st Stage",
        "grade 1st stage": "Grade 1st Stage",
        "grade 2nd stage": "Grade 1st Stage",
        "unburnt": "Unburnt",
        "stones": "Stones",
    }
    return aliases.get(lower, raw)


def is_outward_byproduct(label: str) -> bool:
    return _canonical_outward_grade(label) in OUTWARD_BYPRODUCT_GRADES


def validate_outward_kg_within_inward(outward_kg, inward_kg) -> None:
    """RO bag total cannot exceed gate-receipt our weight."""
    out = Decimal(str(outward_kg or 0))
    inn = Decimal(str(inward_kg or 0))
    if out > inn + Decimal("0.001"):
        raise ValidationError(
            f"GRN total {out} KG cannot exceed inward weight {inn} KG."
        )


def validate_rm_outward_splits(cleaned: list[dict]) -> None:
    """At least one outward bag. A grade, Unburnt, or Stones each counts."""
    rows = [row for row in (cleaned or []) if str(row.get("grade_label") or "").strip()]
    if not rows:
        raise ValidationError("Enter at least one GRN bag.")
    if any(not str(row.get("rotary") or "").strip() for row in rows):
        raise ValidationError("Select Rotary A or Rotary B for every outward bag.")


def is_allowed_outward_grade(db: Session, tenant: TenantContext, label: str) -> bool:
    raw = str(label or "").strip()
    if not raw:
        return False
    allowed = set(outward_split_labels(db, tenant)) | set(OUTWARD_GRADE_LABELS)
    if raw in allowed:
        return True
    return _canonical_outward_grade(raw) in { _canonical_outward_grade(item) for item in allowed }
