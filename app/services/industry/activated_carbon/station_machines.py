"""Plant-floor machine counts from Masters (mst.resource)."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.tenant_context import TenantContext
from app.models.mes_core import Resource
from app.services.mes_core.base import TenantRepository

STATION_SPECS = (
    {
        "key": "destoning",
        "label": "Destoning",
        "aliases": ("deston", "de-ston", "de ston"),
    },
    {
        "key": "screening",
        "label": "Screening",
        "aliases": ("screen",),
    },
    {
        "key": "dedusting",
        "label": "De-dusting",
        "aliases": ("dedust", "de-dust", "de dust"),
    },
    {
        "key": "crushing",
        "label": "Crushing",
        "aliases": ("crush",),
    },
    {
        "key": "demagnetisation",
        "label": "De-magnetisation",
        "aliases": ("demag", "magnet"),
    },
    {
        "key": "blending",
        "label": "Blending",
        "aliases": ("blend",),
    },
    {
        "key": "fg_qc",
        "label": "Finished Goods",
        "aliases": ("finished goods", "fg_qc", "fg-qc", " fg "),
    },
)

STATION_KEYS = tuple(row["key"] for row in STATION_SPECS)


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _meta(resource: Resource) -> dict:
    return resource.metadata_ if isinstance(resource.metadata_, dict) else {}


def _is_floor_machine(resource: Resource) -> bool:
    rtype = (resource.resource_type or "").upper()
    if rtype not in {"MACHINE", "WORKCELL"}:
        return False
    code = (resource.resource_code or "").upper()
    if code.startswith("RES-KILN"):
        return False
    role = str(_meta(resource).get("role") or "").lower()
    if role in {"post_activation", "kiln"}:
        return False
    return True


def _unit_count(resource: Resource) -> int:
    meta = _meta(resource)
    for key in ("unit_count", "machine_count", "loader_count", "capacity", "headcount"):
        raw = meta.get(key)
        if raw in (None, ""):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 1


def station_of(resource: Resource) -> str | None:
    meta = _meta(resource)
    raw = str(meta.get("station") or meta.get("process_key") or "").strip().lower()
    if raw in STATION_KEYS:
        return raw
    hay = f" {(resource.resource_code or '')} {(resource.resource_name or '')} ".lower()
    for spec in STATION_SPECS:
        if any(alias in hay for alias in spec["aliases"]):
            return spec["key"]
    return None


def _matches_station(resource: Resource, station_key: str) -> bool:
    return station_of(resource) == station_key


def _tag_station(resource: Resource, station_key: str) -> bool:
    meta = dict(_meta(resource))
    changed = False
    if str(meta.get("station") or "") != station_key:
        meta["station"] = station_key
        changed = True
    if meta.get("unit_count") in (None, ""):
        meta["unit_count"] = _unit_count(resource)
        changed = True
    if changed:
        resource.metadata_ = meta
        flag_modified(resource, "metadata_")
    return changed


def _next_machine_code(db: Session, tenant: TenantContext) -> str:
    max_n = 0
    for row in (
        db.query(Resource)
        .filter(Resource.tenant_id == tenant.tenant_id)
        .filter(Resource.resource_code.like("RES-MACH-%"))
        .all()
    ):
        match = re.search(r"(\d+)$", str(row.resource_code or ""))
        if match:
            max_n = max(max_n, int(match.group(1)))
    return f"RES-MACH-{max_n + 1:03d}"


def ensure_station_machines(db: Session, tenant: TenantContext) -> None:
    """Create one Masters machine per station when none is registered."""
    repo = _repo(db, tenant)
    rows = [row for row in repo.query(Resource).all() if _is_floor_machine(row)]
    dirty = False
    for spec in STATION_SPECS:
        matched = [row for row in rows if _matches_station(row, spec["key"])]
        if matched:
            for row in matched:
                dirty = _tag_station(row, spec["key"]) or dirty
            continue
        repo.add(
            Resource(
                resource_code=_next_machine_code(db, tenant),
                resource_name=spec["label"],
                resource_type="MACHINE",
                status="ACTIVE",
                metadata_={
                    "role": "machine",
                    "station": spec["key"],
                    "unit_count": 1,
                },
            )
        )
        repo.db.flush()
        dirty = True
    if dirty:
        repo.db.commit()


def station_machine_capacity(db: Session, tenant: TenantContext, station_key: str) -> int:
    ensure_station_machines(db, tenant)
    total = 0
    for row in _repo(db, tenant).query(Resource).all():
        if (row.status or "ACTIVE").upper() != "ACTIVE":
            continue
        if not _is_floor_machine(row):
            continue
        if not _matches_station(row, station_key):
            continue
        total += _unit_count(row)
    return max(total, 1)
