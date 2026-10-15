"""Ensure six kilns (A–F) and four destoners exist in mst.resource."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import Equipment, Resource
from app.models.mes_core.platform import Tenant
from app.services.industry.activated_carbon.codes import plant_today
from app.services.industry.activated_carbon.station_machines import (
    DEFAULT_MONTHLY_CAPACITY_KG,
)
from app.services.mes_core.base import TenantRepository

KILN_LETTERS = "ABCDEF"
DESTONER_COUNT = 4
DESTONER_LOADER_SLOTS = 6
DAILY_CTC_PLAN_KEY = "ac_destoner_daily_ctc"
KILN_SETPOINTS_KEY = "ac_kiln_setpoints"
KILN_SETPOINT_LOG_KEY = "ac_kiln_setpoint_log"
# Monthly designed kg on Masters is the output at this residence. A shorter
# residence raises throughput; a longer residence lowers it.
REFERENCE_RESIDENCE_MIN = 60


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _tenant_resources(db: Session, tenant: TenantContext):
    return _repo(db, tenant).query(Resource)


def _pad_width(existing_codes: list[str], default: int = 2) -> int:
    widths = []
    for code in existing_codes:
        match = re.search(r"(\d+)$", code or "")
        if match:
            widths.append(len(match.group(1)))
    return max(widths) if widths else default


def ensure_six_kilns(db: Session, tenant: TenantContext) -> list[Resource]:
    repo = _repo(db, tenant)
    kilns = (
        _tenant_resources(db, tenant)
        .filter(Resource.resource_code.like("RES-KILN%"))
        .order_by(Resource.resource_code)
        .all()
    )
    pad = _pad_width([row.resource_code or "" for row in kilns], 2)
    by_letter: dict[str, Resource] = {}
    for row in kilns:
        blob = f"{row.resource_name or ''} {row.resource_code or ''}".upper()
        match = re.search(r"\bK(?:ILN|LIN)?[-_\s]*([A-F])\b", blob)
        if match:
            by_letter[match.group(1)] = row
            continue
        digits = re.search(r"(\d+)$", str(row.resource_code or ""))
        if digits:
            n = int(digits.group(1))
            if 1 <= n <= 6:
                by_letter.setdefault(chr(64 + n), row)
    dirty = False
    used_codes = {str(row.resource_code or "").upper() for row in kilns}
    for index, letter in enumerate(KILN_LETTERS, start=1):
        if letter in by_letter:
            row = by_letter[letter]
            meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
            changed = False
            if meta.get("role") != "kiln":
                meta["role"] = "kiln"
                changed = True
            if meta.get("monthly_capacity_kg") in (None, ""):
                meta["monthly_capacity_kg"] = DEFAULT_MONTHLY_CAPACITY_KG
                changed = True
            if changed:
                row.metadata_ = meta
                flag_modified(row, "metadata_")
                dirty = True
            continue
        code = f"RES-KILN-{index:0{pad}d}"
        if code.upper() in used_codes:
            code = f"RES-KILN-{letter}"
        name = f"Kiln {letter}"
        resource = Resource(
            resource_code=code,
            resource_name=name,
            resource_type="MACHINE",
            status="ACTIVE",
            metadata_={
                "role": "kiln",
                "equipment_class": "KILN",
                "monthly_capacity_kg": DEFAULT_MONTHLY_CAPACITY_KG,
            },
        )
        repo.add(resource)
        repo.db.flush()
        eq_code = f"EQ-KILN-{index:0{pad}d}"
        existing_eq = (
            db.query(Equipment)
            .filter(Equipment.tenant_id == tenant.tenant_id)
            .filter(Equipment.equipment_code == eq_code)
            .first()
        )
        if existing_eq is None:
            repo.add(
                Equipment(
                    equipment_code=eq_code,
                    equipment_name=name,
                    resource_id=resource.resource_id,
                    equipment_type="KILN",
                    status="ACTIVE",
                )
            )
        by_letter[letter] = resource
        used_codes.add(code.upper())
        dirty = True
    if dirty:
        repo.db.commit()
    return [by_letter[letter] for letter in KILN_LETTERS if letter in by_letter]


def _is_screening_after_destoning(resource: Resource) -> bool:
    code = (resource.resource_code or "").upper()
    if code.startswith("RES-DESTON"):
        return False
    name = (resource.resource_name or "").upper()
    return "AFTER DESTON" in name or "SCREENING AFTER" in name


def _is_destoner(resource: Resource) -> bool:
    if _is_screening_after_destoning(resource):
        return False
    code = (resource.resource_code or "").upper()
    if code.startswith("RES-DESTON"):
        return True
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    role = str(meta.get("role") or "").lower()
    station = str(meta.get("station") or "").lower()
    if role == "destoning" or station == "destoning":
        return True
    name = (resource.resource_name or "").upper()
    return (
        name in {"DE-STONER", "DESTONER", "DESTONING"}
        or name.startswith("DESTONER ")
        or name.startswith("DE-STONER ")
    )


def _repair_misclassified_destoners(db: Session, tenant: TenantContext) -> None:
    """Undo destoner tagging on Screening-after-Destoning machines."""
    repo = _repo(db, tenant)
    dirty = False
    for row in _tenant_resources(db, tenant).all():
        if not _is_screening_after_destoning(row):
            continue
        meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
        changed = False
        if meta.get("station") == "destoning":
            meta["station"] = "screening_after_destoning"
            changed = True
        if meta.get("role") == "destoning":
            meta.pop("role", None)
            changed = True
        if changed:
            row.metadata_ = meta
            flag_modified(row, "metadata_")
            dirty = True
    if dirty:
        repo.db.commit()


def list_destoner_resources(db: Session, tenant: TenantContext) -> list[Resource]:
    rows = [row for row in _tenant_resources(db, tenant).all() if _is_destoner(row)]
    return sorted(rows, key=lambda row: row.resource_code or "")


def ensure_four_destoners(db: Session, tenant: TenantContext) -> list[Resource]:
    _repair_misclassified_destoners(db, tenant)
    repo = _repo(db, tenant)
    destoners = list_destoner_resources(db, tenant)
    dirty = False
    for row in destoners:
        meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
        changed = False
        if meta.get("role") != "destoning":
            meta["role"] = "destoning"
            changed = True
        if meta.get("station") != "destoning":
            meta["station"] = "destoning"
            changed = True
        if meta.get("monthly_capacity_kg") in (None, ""):
            meta["monthly_capacity_kg"] = DEFAULT_MONTHLY_CAPACITY_KG
            changed = True
        if meta.get("unit_count") in (None, ""):
            meta["unit_count"] = DESTONER_LOADER_SLOTS
            changed = True
        if (
            str(row.resource_code or "").upper() == "RES-DESTON-01"
            and (row.resource_name or "").strip().lower() == "de-stoner"
        ):
            row.resource_name = "Destoner 1"
            changed = True
        if changed:
            row.metadata_ = meta
            flag_modified(row, "metadata_")
            dirty = True
    used = {str(row.resource_code or "").upper() for row in destoners}
    for index in range(1, DESTONER_COUNT + 1):
        code = f"RES-DESTON-{index:02d}"
        if code.upper() in used:
            continue
        name = f"Destoner {index}"
        resource = Resource(
            resource_code=code,
            resource_name=name,
            resource_type="MACHINE",
            status="ACTIVE",
            metadata_={
                "role": "destoning",
                "station": "destoning",
                "unit_count": DESTONER_LOADER_SLOTS,
                "monthly_capacity_kg": DEFAULT_MONTHLY_CAPACITY_KG,
            },
        )
        repo.add(resource)
        destoners.append(resource)
        used.add(code.upper())
        dirty = True
    if dirty:
        repo.db.flush()
        repo.db.commit()
    return list_destoner_resources(db, tenant)


def destoner_daily_ctc(resource: Resource, today: date | None = None) -> str | None:
    """CTC stored on the destoner resource for the given plant day."""
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    assigned_date = str(meta.get("daily_ctc_date") or "").strip()
    if assigned_date != str(today or date.today()):
        return None
    raw = meta.get("daily_ctc")
    if raw in (None, ""):
        return None
    return str(raw)


def destoner_daily_mesh(resource: Resource, today: date | None = None) -> str | None:
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    assigned_date = str(meta.get("daily_mesh_date") or meta.get("daily_ctc_date") or "").strip()
    if assigned_date != str(today or date.today()):
        return None
    raw = meta.get("daily_mesh")
    if raw in (None, ""):
        return None
    return str(raw).strip().upper()


def destoner_daily_ctc_meta(resource: Resource, today: date | None = None) -> dict:
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    assigned_date = str(meta.get("daily_ctc_date") or meta.get("daily_mesh_date") or "").strip() or None
    ctc = destoner_daily_ctc(resource, today)
    mesh = destoner_daily_mesh(resource, today)
    return {
        "assigned_ctc": ctc,
        "assigned_mesh": mesh,
        "assigned_date": assigned_date if (ctc or mesh) else None,
        "assigned_by": (str(meta.get("daily_ctc_by") or "") or None) if (ctc or mesh) else None,
    }


def tenant_daily_ctc_plan(
    db: Session, tenant: TenantContext, today: date | None = None
) -> dict[str, dict]:
    """Today's destoner CTC plan on the tenant record (survives machine-metadata refreshes)."""
    day = str(today or plant_today(tenant.timezone))
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        return {}
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(DAILY_CTC_PLAN_KEY)
    if not isinstance(block, dict):
        return {}
    day_block = block.get(day)
    if not isinstance(day_block, dict):
        return {}
    out: dict[str, dict] = {}
    for code, raw in day_block.items():
        if isinstance(raw, dict):
            ctc = raw.get("ctc")
            mesh = str(raw.get("mesh") or "").strip().upper() or None
            if ctc in (None, "") and not mesh:
                continue
            out[str(code)] = {
                "ctc": str(ctc) if ctc not in (None, "") else None,
                "mesh": mesh,
                "by": raw.get("by"),
            }
        elif raw not in (None, ""):
            out[str(code)] = {"ctc": str(raw), "mesh": None, "by": None}
    return out


def save_tenant_daily_ctc_plan(
    db: Session,
    tenant: TenantContext,
    assignments: dict[str, dict],
    *,
    today: date | None = None,
) -> dict[str, dict]:
    day = str(today or plant_today(tenant.timezone))
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        raise ValidationError("Plant tenant was not found.")
    meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
    day_block: dict[str, dict] = {}
    for code, payload in (assignments or {}).items():
        ctc = (payload or {}).get("ctc")
        mesh = str((payload or {}).get("mesh") or "").strip().upper() or None
        if ctc in (None, "") and not mesh:
            continue
        day_block[str(code)] = {
            "ctc": str(ctc) if ctc not in (None, "") else None,
            "mesh": mesh,
            "by": (payload or {}).get("by"),
        }
    meta[DAILY_CTC_PLAN_KEY] = {day: day_block}
    row.metadata_ = meta
    flag_modified(row, "metadata_")
    return day_block


def destoner_plan_meta(
    resource: Resource,
    plan: dict[str, dict] | None,
    today: date | None = None,
) -> dict:
    day = str(today or date.today())
    entry = (plan or {}).get(str(resource.resource_code or ""))
    fallback = destoner_daily_ctc_meta(resource, today)
    if not entry:
        return fallback
    ctc = entry.get("ctc")
    mesh = str(entry.get("mesh") or "").strip().upper() or None
    if ctc in (None, "") and not mesh:
        return fallback
    return {
        "assigned_ctc": str(ctc) if ctc not in (None, "") else fallback.get("assigned_ctc"),
        "assigned_mesh": mesh or fallback.get("assigned_mesh"),
        "assigned_date": day,
        "assigned_by": str(entry.get("by") or "") or fallback.get("assigned_by"),
    }


def set_destoner_daily_ctc(
    resource: Resource,
    ctc: str | None,
    *,
    mesh: str | None = None,
    user_id: str | None = None,
    today: date | None = None,
) -> None:
    meta = dict(resource.metadata_ if isinstance(resource.metadata_, dict) else {})
    day = str(today or date.today())
    value = str(ctc).strip() if ctc not in (None, "") else ""
    mesh_code = str(mesh).strip().upper() if mesh not in (None, "") else ""
    if value:
        meta["daily_ctc"] = value
        meta["daily_ctc_date"] = day
        if user_id:
            meta["daily_ctc_by"] = str(user_id)
    else:
        if str(meta.get("daily_ctc_date") or "") == day:
            meta.pop("daily_ctc", None)
            meta.pop("daily_ctc_date", None)
            meta.pop("daily_ctc_by", None)
    if mesh_code:
        meta["daily_mesh"] = mesh_code
        meta["daily_mesh_date"] = day
        if user_id:
            meta["daily_ctc_by"] = str(user_id)
    else:
        if str(meta.get("daily_mesh_date") or "") == day:
            meta.pop("daily_mesh", None)
            meta.pop("daily_mesh_date", None)
    resource.metadata_ = meta
    flag_modified(resource, "metadata_")


def next_destoner_index(db: Session, tenant: TenantContext) -> int:
    used = []
    for row in list_destoner_resources(db, tenant):
        match = re.search(r"(\d+)$", str(row.resource_code or ""))
        if match:
            used.append(int(match.group(1)))
    return (max(used) + 1) if used else 1


def create_destoner_resource(
    db: Session,
    tenant: TenantContext,
    *,
    name: str,
    unit_count: int = DESTONER_LOADER_SLOTS,
    monthly_capacity_kg: int = DEFAULT_MONTHLY_CAPACITY_KG,
) -> Resource:
    repo = _repo(db, tenant)
    label = (name or "").strip()
    if not label:
        raise ValidationError("Destoner name is required")
    ensure_four_destoners(db, tenant)
    idx = next_destoner_index(db, tenant)
    code = f"RES-DESTON-{idx:02d}"
    existing = (
        _tenant_resources(db, tenant)
        .filter(Resource.resource_code == code)
        .first()
    )
    if existing is not None:
        idx = next_destoner_index(db, tenant) + 1
        code = f"RES-DESTON-{idx:02d}"
    resource = Resource(
        resource_code=code,
        resource_name=label,
        resource_type="MACHINE",
        status="ACTIVE",
        metadata_={
            "role": "destoning",
            "station": "destoning",
            "unit_count": max(int(unit_count or DESTONER_LOADER_SLOTS), 1),
            "monthly_capacity_kg": int(monthly_capacity_kg or DEFAULT_MONTHLY_CAPACITY_KG),
        },
    )
    repo.add(resource)
    repo.db.flush()
    eq_code = f"EQ-DESTON-{idx:02d}"
    existing_eq = (
        db.query(Equipment)
        .filter(Equipment.tenant_id == tenant.tenant_id)
        .filter(Equipment.equipment_code == eq_code)
        .first()
    )
    if existing_eq is None:
        repo.add(
            Equipment(
                equipment_code=eq_code,
                equipment_name=label,
                resource_id=resource.resource_id,
                equipment_type="DESTONER",
                status="ACTIVE",
            )
        )
    repo.db.commit()
    repo.db.refresh(resource)
    return resource


def designed_monthly_kg_for_residence(
    monthly_capacity_kg: int | None, residence_time_min: object
) -> int:
    """Kiln designed kg for the month at the standing residence time.

    Masters monthly capacity is the output when residence is 60 minutes.
    Designed kg = monthly capacity × (60 ÷ residence minutes).
    """
    base = int(monthly_capacity_kg or 0)
    if base < 1:
        base = DEFAULT_MONTHLY_CAPACITY_KG
    try:
        residence = float(residence_time_min)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return base
    if residence <= 0:
        return base
    return max(1, int(round(base * REFERENCE_RESIDENCE_MIN / residence)))


def kiln_setpoint_plan(db: Session, tenant: TenantContext) -> dict[str, dict]:
    """Standing kiln parameters. They stay until changed — not a daily plan."""
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        return {}
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(KILN_SETPOINTS_KEY)
    if not isinstance(block, dict):
        return {}
    out: dict[str, dict] = {}
    for code, raw in block.items():
        if not isinstance(raw, dict):
            continue
        params = raw.get("parameters")
        if not isinstance(params, dict):
            continue
        cleaned: dict[str, float] = {}
        for key, value in params.items():
            if "scrap" in str(key).lower() or value in (None, ""):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number < 0:
                continue
            cleaned[str(key)] = number
        out[str(code)] = {
            "parameters": cleaned,
            "by": raw.get("by"),
            "updated_at": raw.get("updated_at"),
        }
    return out


def kiln_setpoint_history(db: Session, tenant: TenantContext) -> list[dict]:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        return []
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    raw = meta.get(KILN_SETPOINT_LOG_KEY)
    if not isinstance(raw, list):
        return []
    return [item for item in reversed(raw) if isinstance(item, dict)]


def residence_minutes_for(plan: dict[str, dict] | None, resource_code: str) -> float | None:
    entry = (plan or {}).get(str(resource_code or "")) or {}
    params = entry.get("parameters") if isinstance(entry, dict) else None
    if not isinstance(params, dict):
        return None
    raw = params.get("residence_time_min")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def save_kiln_setpoint_plan(
    db: Session,
    tenant: TenantContext,
    assignments: dict[str, dict],
) -> dict[str, dict]:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        raise ValidationError("Plant tenant was not found.")
    meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous_block = meta.get(KILN_SETPOINTS_KEY) if isinstance(meta.get(KILN_SETPOINTS_KEY), dict) else {}
    log = [item for item in (meta.get(KILN_SETPOINT_LOG_KEY) or []) if isinstance(item, dict)]
    block: dict[str, dict] = {}
    for code, payload in (assignments or {}).items():
        params: dict[str, float] = {}
        for key, value in ((payload or {}).get("parameters") or {}).items():
            if "scrap" in str(key).lower() or value in (None, ""):
                continue
            params[str(key)] = float(value)
        if not params:
            continue
        stamped = (payload or {}).get("updated_at") or now
        block[str(code)] = {
            "parameters": params,
            "by": (payload or {}).get("by"),
            "updated_at": stamped,
        }
        previous = (previous_block.get(str(code)) or {}).get("parameters") if isinstance(previous_block.get(str(code)), dict) else {}
        if previous != params:
            log.append(
                {
                    "kiln_resource_code": str(code),
                    "at": stamped,
                    "by": (payload or {}).get("by"),
                    "parameters": params,
                }
            )
    meta[KILN_SETPOINTS_KEY] = block
    meta[KILN_SETPOINT_LOG_KEY] = log[-200:]
    row.metadata_ = meta
    flag_modified(row, "metadata_")
    return block


def ensure_plant_equipment(db: Session, tenant: TenantContext) -> None:
    ensure_six_kilns(db, tenant)
    ensure_four_destoners(db, tenant)
