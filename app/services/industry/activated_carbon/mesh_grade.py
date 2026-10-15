"""Mesh configuration → output grades for destoning quality.

Mesh types A–E are the plant catalog. Grade labels are master-driven and
may be edited. Destoning QC shows only the grades for the selected mesh.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import Tenant

META_KEY = "ac_mesh_grade_map"
DESTONING_STATION = "destoning"

DEFAULT_MESH_CONFIGS: list[dict[str, Any]] = [
    {"code": "A", "label": "Mesh configuration A", "grades": ["+3", "3/4", "-4"]},
    {"code": "B", "label": "Mesh configuration B", "grades": ["+4", "4/8", "-8"]},
    {"code": "C", "label": "Mesh configuration C", "grades": ["+8", "8/12", "-12"]},
    {"code": "D", "label": "Mesh configuration D", "grades": ["+12", "12/30", "-30"]},
    {
        "code": "E",
        "label": "Mesh configuration E",
        "grades": ["+3", "3/4", "4/8", "8/12", "12/30", "-30"],
    },
]


def default_mesh_grade_map() -> dict[str, Any]:
    configs = [dict(row, grades=list(row["grades"])) for row in DEFAULT_MESH_CONFIGS]
    return {
        "configurations": configs,
        "rows": _rows_from_configurations(configs),
        "source": "GR_CARBONS",
        "notes": "Destoning quality shows the grades for the selected mesh configuration.",
    }


def grade_slug(label: str) -> str:
    text = str(label or "").strip().replace("\u2212", "-")
    return text.replace("+", "plus_").replace("-", "minus_").replace("/", "_")


def deston_grade_param_code(label: str) -> str:
    return f"deston_qc_{grade_slug(label)}_kg"


def _tenant_row(db: Session, tenant: TenantContext) -> Tenant:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        row = db.query(Tenant).filter(Tenant.tenant_id == tenant.tenant_id).first()
    if row is None:
        raise ValueError(f"Tenant '{tenant.tenant_code}' not found")
    return row


def _normalize_grades(raw) -> list[str]:
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.replace(";", ",").split(",")]
    else:
        parts = [str(part).strip() for part in (raw or [])]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        key = part.replace("\u2212", "-").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(part.replace("\u2212", "-"))
    return out


def _normalize_configurations(raw_configs, rows) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_configs or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("mesh") or "").strip().upper()
        if not code or code in seen:
            continue
        label = str(item.get("label") or item.get("mesh_label") or "").strip()
        if not label:
            label = f"Mesh configuration {code}"
        grades = _normalize_grades(item.get("grades") or item.get("output_grades"))
        seen.add(code)
        configs.append({"code": code, "label": label, "grades": grades})
    if configs:
        return configs
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for row in rows or []:
        mesh = str(row.get("mesh") or "").strip()
        grade = str(row.get("grade") or "").strip()
        if not mesh or not grade:
            continue
        key = mesh.upper() if len(mesh) <= 2 else mesh
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        if grade not in grouped[key]:
            grouped[key].append(grade)
    for key in order:
        code = key if len(key) <= 2 else key[:1]
        configs.append(
            {
                "code": code.upper(),
                "label": key if len(key) > 2 else f"Mesh configuration {code.upper()}",
                "grades": grouped[key],
            }
        )
    return configs or [dict(row, grades=list(row["grades"])) for row in DEFAULT_MESH_CONFIGS]


def _rows_from_configurations(configs: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for cfg in configs:
        for grade in cfg.get("grades") or []:
            rows.append(
                {
                    "mesh": str(cfg.get("code") or ""),
                    "grade": str(grade),
                    "station": DESTONING_STATION,
                }
            )
    return rows


def _normalize_rows(rows) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        mesh = str(raw.get("mesh") or raw.get("mesh_label") or "").strip()
        grade = str(raw.get("grade") or raw.get("grade_label") or "").strip()
        station = str(raw.get("station") or raw.get("source") or "").strip()
        if not mesh and not grade:
            continue
        key = (mesh.lower(), grade.lower(), station.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"mesh": mesh, "grade": grade, "station": station})
    return out


def normalize_mesh_grade_map(payload: dict | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    rows = _normalize_rows(data.get("rows"))
    configs = _normalize_configurations(data.get("configurations"), rows)
    notes = str(data.get("notes") or "").strip()
    if not notes or "waiting for gr carbons mesh-to-grade" in notes.lower():
        notes = default_mesh_grade_map()["notes"]
    source = str(data.get("source") or "").strip() or "GR_CARBONS"
    return {
        "configurations": configs,
        "rows": _rows_from_configurations(configs),
        "source": source,
        "notes": notes,
    }


def get_mesh_grade_map(db: Session, tenant: TenantContext) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(META_KEY)
    if not isinstance(block, dict):
        return default_mesh_grade_map()
    try:
        cleaned = normalize_mesh_grade_map(block)
    except ValidationError:
        return default_mesh_grade_map()
    if not cleaned.get("configurations"):
        return default_mesh_grade_map()
    return cleaned


def save_mesh_grade_map(db: Session, tenant: TenantContext, payload: dict) -> dict[str, Any]:
    cleaned = normalize_mesh_grade_map(payload)
    row = _tenant_row(db, tenant)
    meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
    meta[META_KEY] = cleaned
    row.metadata_ = meta
    flag_modified(row, "metadata_")
    db.commit()
    db.refresh(row)
    return cleaned


def ensure_mesh_grade_map(db: Session, tenant: TenantContext) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(META_KEY)
    if isinstance(block, dict):
        cleaned = normalize_mesh_grade_map(block)
        has_grades = any(cfg.get("grades") for cfg in cleaned.get("configurations") or [])
        if has_grades and (block.get("configurations") or block.get("rows")):
            return get_mesh_grade_map(db, tenant)
    return save_mesh_grade_map(db, tenant, default_mesh_grade_map())


def grades_for_mesh(db: Session, tenant: TenantContext, mesh: str | None = None) -> list[str]:
    """Return output grades for a mesh configuration code or label."""
    catalog = get_mesh_grade_map(db, tenant)
    wanted = str(mesh or "").strip().lower()
    if not wanted:
        return []
    for cfg in catalog.get("configurations") or []:
        code = str(cfg.get("code") or "").strip().lower()
        label = str(cfg.get("label") or "").strip().lower()
        if wanted in {code, label, f"mesh configuration {code}"}:
            return [str(grade) for grade in (cfg.get("grades") or []) if grade]
    grades: list[str] = []
    for row in catalog.get("rows") or []:
        if str(row.get("mesh") or "").strip().lower() != wanted:
            continue
        grade = str(row.get("grade") or "").strip()
        if grade and grade not in grades:
            grades.append(grade)
    return grades


def resolve_mesh_code(catalog: dict | None, raw: Any) -> str | None:
    wanted = str(raw or "").strip()
    if not wanted:
        return None
    for cfg in (catalog or {}).get("configurations") or []:
        code = str(cfg.get("code") or "").strip()
        label = str(cfg.get("label") or "").strip()
        if wanted.upper() == code.upper() or wanted.lower() == label.lower():
            return code.upper()
    raise ValidationError(f"Unknown mesh configuration '{wanted}'.")
