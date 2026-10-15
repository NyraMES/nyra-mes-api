"""Shared live-load for post-activation shop steps.

Destoning output bags can be loaded on screening, crushing, de-dusting,
de-magnetisation, or blending. A bag loaded or consumed on
any of those stations is hidden from every other loader.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import Resource
from app.schemas.mes_core.schemas import (
    AcPostActivationBagOut,
    AcPostActivationLoadCreate,
    AcPostActivationLoadEventOut,
    AcPostActivationOutputCreate,
    AcPostActivationQualityBagOut,
    AcPostActivationQualityOut,
    AcPostActivationQualitySave,
    AcPostActivationQualitySectionOut,
    AcPostActivationStateOut,
    TripleCreate,
)
from app.services.industry.activated_carbon.codes import next_post_activation_bag_code, plant_today
from app.services.mes_core.base import TenantRepository
from app.services.industry.activated_carbon.station_machines import (
    station_monthly_capacity_kg,
)

# Bags that can sit on one post-activation loader. Machine count in Masters is not this limit.
POST_ACTIVATION_LOADER_CAPACITY = 6
EXKLIN_GRADE = "Exklin"
EXKLIN_ONLY_PROCESSES = frozenset({"dedusting", "demagnetisation"})

QUALITY_SECTION_KEYS = (
    "screening",
    "dedusting",
    "crushing",
    "demagnetisation",
    "blending",
)

QUALITY_SECTION_LABELS = {
    "screening": "Screening",
    "blending": "Blending",
    "dedusting": "De-dusting",
    "demagnetisation": "De-Magnetize",
    "crushing": "Crushing",
}

DESTINATION_TO_PROCESS = {
    "screening after destoning": "screening",
    "screening_after_destoning": "screening",
    "sad": "screening",
    "destoning": "destoning",
    "destone": "destoning",
    "destone again": "destoning",
    "destoning again": "destoning",
    "screening": "screening",
    "crushing": "crushing",
    "de-dusting": "dedusting",
    "dedusting": "dedusting",
    "de-magnetize": "demagnetisation",
    "de-magnetise": "demagnetisation",
    "demagnetisation": "demagnetisation",
    "blending": "blending",
}

POST_ACTIVATION_PROCESSES = {
    "screening_after_destoning": {
        "label": "Screening after Destoning",
        "prefix": "SD",
        "operation_code": "OP-POST-SAD",
        "process_step": "SCREENING_AFTER_DESTONING",
        "bag_kind": "sadBag",
    },
    "screening": {
        "label": "Screening",
        "prefix": "SC",
        "operation_code": "OP-POST-SCREEN",
        "process_step": "SCREENING",
        "bag_kind": "screenBag",
    },
    "dedusting": {
        "label": "De-dusting",
        "prefix": "DD",
        "operation_code": "OP-DEDUST",
        "process_step": "DRYING",
        "bag_kind": "dedustBag",
    },
    "crushing": {
        "label": "Crushing",
        "prefix": "CR",
        "operation_code": "OP-CRUSH-LOAD",
        "process_step": "GRINDING",
        "bag_kind": "crushBag",
    },
    "demagnetisation": {
        "label": "De-magnetisation",
        "prefix": "DM",
        "operation_code": "OP-DEMAG",
        "process_step": "GRINDING",
        "bag_kind": "demagBag",
    },
    "blending": {
        "label": "Blending",
        "prefix": "BL",
        "operation_code": "OP-BLEND",
        "process_step": "GRADE_SEPARATION",
        "bag_kind": "blendBag",
    },
}


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _tenant_resources(db: Session, tenant: TenantContext):
    return _repo(db, tenant).query(Resource)


def resolve_post_activation_process(process: str) -> dict[str, str]:
    key = str(process or "").strip().lower()
    spec = POST_ACTIVATION_PROCESSES.get(key)
    if not spec:
        raise ValidationError(f"Unknown post-activation process '{process}'.")
    return {"key": key, **spec}


def _ensure_post_activation_resource(db: Session, tenant: TenantContext) -> Resource:
    repo = _repo(db, tenant)
    for resource in _tenant_resources(db, tenant).all():
        meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
        role = str(meta.get("role") or "").lower()
        code = (resource.resource_code or "").upper()
        if role == "post_activation" or code == "RES-POSTACT-01":
            return resource
    row = Resource(
        resource_code="RES-POSTACT-01",
        resource_name="Post activation",
        resource_type="MACHINE",
        status="ACTIVE",
        metadata_={"role": "post_activation", "stations": {}},
    )
    repo.add(row)
    repo.db.flush()
    return row


def _ensure_destoner_resource(db: Session, tenant: TenantContext) -> Resource | None:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    destoners = ac_plant_equipment.list_destoner_resources(db, tenant)
    if destoners:
        return destoners[0]
    destoners = ac_plant_equipment.ensure_four_destoners(db, tenant)
    return destoners[0] if destoners else None


def _list_destoner_resources(db: Session, tenant: TenantContext) -> list[Resource]:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    rows = ac_plant_equipment.list_destoner_resources(db, tenant)
    return rows or ac_plant_equipment.ensure_four_destoners(db, tenant)


def _copy_station(row: dict) -> dict:
    return {
        "loaded_bags": [dict(item) for item in (row.get("loaded_bags") or []) if isinstance(item, dict)],
        "output_bags": [dict(item) for item in (row.get("output_bags") or []) if isinstance(item, dict)],
        "load_events": [dict(item) for item in (row.get("load_events") or []) if isinstance(item, dict)],
        "selected_mesh": str(row.get("selected_mesh") or "").strip() or None,
    }


def _stations(meta: dict) -> dict[str, dict]:
    raw = meta.get("stations") if isinstance(meta.get("stations"), dict) else {}
    stations: dict[str, dict] = {}
    for key in POST_ACTIVATION_PROCESSES:
        row = raw.get(key) if isinstance(raw.get(key), dict) else {}
        stations[key] = _copy_station(row)
    for key, row in raw.items():
        if key in stations or not isinstance(row, dict):
            continue
        stations[key] = _copy_station(row)
    return stations


def _is_in_stock_destination(raw: str | None) -> bool:
    text = re.sub(r"[^a-z0-9]+", " ", str(raw or "").strip().lower()).strip()
    return text in {
        "in stock",
        "instock",
        "finished goods",
        "finished goods qc",
        "fg",
        "fg qc",
    }


def _work_order_of(row: dict | None) -> str | None:
    if not isinstance(row, dict):
        return None
    code = str(row.get("work_order_code") or "").strip()
    return code or None


def active_post_work_order(loaded, waiting, outputs) -> str | None:
    """One work order per step so the lists stay on the job in progress.

    The loader wins. With an empty loader, the oldest bag still waiting is next.
    With nothing waiting, the latest output on this step is the one shown.
    """
    for row in loaded or []:
        code = _work_order_of(row)
        if code:
            return code
    waiting_rows = [row for row in (waiting or []) if _work_order_of(row)]
    if waiting_rows:
        waiting_rows.sort(key=lambda row: str(row.get("created_at") or row.get("loaded_at") or ""))
        return _work_order_of(waiting_rows[0])
    produced = [row for row in (outputs or []) if _work_order_of(row)]
    if produced:
        produced.sort(key=lambda row: str(row.get("created_at") or ""))
        return _work_order_of(produced[-1])
    return None


def rows_for_active_work_order(rows, code: str | None):
    if not code:
        return list(rows or [])
    return [row for row in (rows or []) if _work_order_of(row) == code]


def _row_kg(row: dict | None) -> Decimal:
    if not isinstance(row, dict):
        return Decimal("0")
    try:
        return Decimal(str(row.get("quantity_kg") or row.get("kg") or 0))
    except Exception:
        return Decimal("0")


def station_loaded_kg(station: dict | None) -> Decimal:
    return sum((_row_kg(row) for row in ((station or {}).get("loaded_bags") or [])), Decimal("0"))


def current_load_output_bags(station: dict | None) -> list[dict]:
    """Output tags made from the bags on the loader now. Older tags stay stored and off this screen."""
    bags = (station or {}).get("loaded_bags") or []
    loaded_codes = {str(row.get("bag_code") or "") for row in bags if isinstance(row, dict) and row.get("bag_code")}
    if not loaded_codes:
        return []
    rows: list[dict] = []
    for row in (station or {}).get("output_bags") or []:
        if not isinstance(row, dict) or not row.get("bag_code"):
            continue
        inputs = {str(code) for code in (row.get("input_bag_codes") or []) if code}
        if inputs & loaded_codes:
            rows.append(row)
    return rows


def station_current_output_kg(station: dict | None) -> Decimal:
    return sum((_row_kg(row) for row in current_load_output_bags(station)), Decimal("0"))


_INDIA = timezone(timedelta(hours=5, minutes=30))


def _plant_zone(tz_name: str | None):
    """Plant clock. India has no daylight saving, so the fixed offset matches Asia/Kolkata."""
    name = (tz_name or "").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        if name in {"Asia/Kolkata", "Asia/Calcutta"}:
            return _INDIA
        return timezone.utc


def bag_plant_date(row: dict | None, tz_name: str | None) -> date | None:
    """Calendar date of created_at in the plant timezone. Stored times stay UTC."""
    if not isinstance(row, dict):
        return None
    raw = str(row.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_plant_zone(tz_name)).date()


def bag_on_plant_day(row: dict | None, *, tz_name: str | None, today: date | None = None) -> bool:
    """True when the bag was created on the plant's current day."""
    local = bag_plant_date(row, tz_name)
    if local is None:
        return False
    day = today or plant_today(tz_name)
    return local == day


def bags_on_plant_day(rows, *, tz_name: str | None, today: date | None = None) -> list[dict]:
    return [row for row in (rows or []) if bag_on_plant_day(row, tz_name=tz_name, today=today)]


def output_rows_for_scope(rows, *, tz_name: str | None, scope: str | None) -> list[dict]:
    """Shop screens stay on the plant day. Dashboards and reports keep the saved history."""
    stored = [row for row in (rows or []) if isinstance(row, dict) and row.get("bag_code")]
    if (scope or "today").strip().lower() == "all":
        return stored
    return bags_on_plant_day(stored, tz_name=tz_name)


def screening_mesh_for_load(station: dict | None, mesh_code: str) -> str:
    """Mesh is chosen before a screening bag is loaded, and stays until the loader is empty."""
    code = str(mesh_code or "").strip().upper()
    if not code:
        raise ValidationError("Choose a mesh before loading a bag.")
    current = str((station or {}).get("selected_mesh") or "").strip().upper()
    if current and current != code:
        raise ValidationError(
            f"Screening is already on mesh {current}. Unload the bags before changing mesh."
        )
    return code


def assert_output_within_loaded(station: dict | None, quantity: Decimal, label: str) -> None:
    loaded_kg = station_loaded_kg(station)
    if loaded_kg <= 0:
        raise ValidationError(f"Load bags onto {label} first.")
    remaining = loaded_kg - station_current_output_kg(station)
    qty = Decimal(str(quantity))
    if qty > remaining + Decimal("0.001"):
        raise ValidationError(
            f"{label} output cannot exceed loaded ({loaded_kg} KG). Remaining: {remaining} KG."
        )


def _grade_on_mesh(grade: str, allowed: list[str]) -> bool:
    wanted = str(grade or "").replace("\u2212", "-").strip().lower()
    return any(str(item).replace("\u2212", "-").strip().lower() == wanted for item in allowed)


def _lookup_work_order_ctc(db: Session, tenant: TenantContext, code: str | None, cache: dict | None = None):
    from app.services.industry.activated_carbon.work_orders import lookup_work_order_ctc

    return lookup_work_order_ctc(db, tenant, code, cache)


def _normalize_destination_label(raw: str | None) -> str | None:
    text = re.sub(r"[^a-z0-9]+", " ", str(raw or "").strip().lower()).strip()
    if not text or _is_in_stock_destination(text):
        return None
    aliases = {
        "screening after destoning": "screening",
        "screening_after_destoning": "screening",
        "sad": "screening",
        "destoning": "destoning",
        "destone": "destoning",
        "destone again": "destoning",
        "destoning again": "destoning",
        "screening": "screening",
        "crushing": "crushing",
        "de dusting": "dedusting",
        "dedusting": "dedusting",
        "dedust": "dedusting",
        "de magnetize": "demagnetisation",
        "de magnetise": "demagnetisation",
        "demagnetisation": "demagnetisation",
        "demagnetize": "demagnetisation",
        "demag": "demagnetisation",
        "blending": "blending",
    }
    if text in aliases:
        return aliases[text]
    return DESTINATION_TO_PROCESS.get(text) or DESTINATION_TO_PROCESS.get(str(raw or "").strip().lower())


def _values_destination_raw(values: dict | None) -> str:
    data = values if isinstance(values, dict) else {}
    for key in ("deston_qc_destination", "post_qc_destination", "destination"):
        if data.get(key) not in (None, ""):
            return str(data.get(key))
    for key, value in data.items():
        if "destination" in str(key).lower() and value not in (None, ""):
            return str(value)
    return ""


def _values_destination(values: dict | None) -> str | None:
    return _normalize_destination_label(_values_destination_raw(values))


def _bag_destination_raw(bag: dict) -> str:
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    dest_values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
    raw = _values_destination_raw(dest_values)
    if raw:
        return raw
    quality = _bag_qc(bag)
    quality_values = quality.get("values") if isinstance(quality.get("values"), dict) else {}
    raw = _values_destination_raw(quality_values)
    if raw:
        return raw
    for key in ("deston_qc_destination", "post_qc_destination", "destination"):
        if bag.get(key) not in (None, ""):
            return str(bag.get(key))
    return ""


def _bag_qc_saved(bag: dict) -> bool:
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    if qc.get("saved_at"):
        return True
    quality = _bag_qc(bag)
    return bool(quality.get("saved_at"))


def _bag_remaining_kg(bag: dict) -> Decimal:
    qty = Decimal(str(bag.get("quantity_kg") or 0))
    dispatched = Decimal(str(bag.get("dispatched_kg") or 0))
    return max(qty - dispatched, Decimal("0"))


def bag_is_available_in_stock(bag: dict) -> bool:
    """True when Quality destination is In Stock and the bag is not fully dispatched."""
    if bag.get("dispatched"):
        return False
    if _bag_remaining_kg(bag) <= 0:
        return False
    if not _bag_qc_saved(bag):
        return False
    return _is_in_stock_destination(_bag_destination_raw(bag))


def _in_stock_bag_row(bag: dict, *, source: str) -> dict:
    return {
        "bag_code": str(bag.get("bag_code") or ""),
        "quantity_kg": Decimal(str(bag.get("quantity_kg") or 0)),
        "remaining_kg": _bag_remaining_kg(bag),
        "grade": bag.get("grade") or _destoning_grade(bag) or "In Stock",
        "lot_code": bag.get("lot_code"),
        "work_order_code": _work_order_of(bag),
        "created_at": bag.get("created_at"),
        "source": source,
    }


def _destoning_dest_map(db: Session, tenant: TenantContext) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for bag in _destoning_output_bags(db, tenant):
        code = str(bag.get("bag_code") or "")
        dest = _destoning_destination(bag)
        if code and dest:
            mapped[code] = dest
    return mapped


def _is_destoning_bag_code(code: str) -> bool:
    return str(code or "").upper().startswith("DS_")


def _reconcile_station_loads(stations: dict[str, dict], dest_map: dict[str, str]) -> None:
    """Keep destoning bags only on the tab matching Destoning Quality destination."""
    for key, station in stations.items():
        next_loaded = []
        for row in station.get("loaded_bags") or []:
            code = str(row.get("bag_code") or "")
            dest = dest_map.get(code)
            if dest is not None and dest != key:
                continue
            if dest is None and _is_destoning_bag_code(code):
                continue
            next_loaded.append(row)
        keep = {str(row.get("bag_code") or "") for row in next_loaded if row.get("bag_code")}
        station["loaded_bags"] = next_loaded
        station["load_events"] = [
            event
            for event in (station.get("load_events") or [])
            if str(event.get("bag_code") or "") in keep
        ]


def _remove_bag_from_other_stations(stations: dict[str, dict], process_key: str, code: str) -> None:
    for key, station in stations.items():
        if key == process_key:
            continue
        before = station.get("loaded_bags") or []
        station["loaded_bags"] = [
            row for row in before if str(row.get("bag_code") or "") != code
        ]
        if len(station["loaded_bags"]) != len(before):
            station["load_events"] = [
                event
                for event in (station.get("load_events") or [])
                if str(event.get("bag_code") or "") != code
            ]


def _busy_bag_codes(stations: dict[str, dict], dest_map: dict[str, str] | None = None) -> set[str]:
    dest_map = dest_map or {}
    busy: set[str] = set()
    for key, station in stations.items():
        used: set[str] = set()
        for row in station.get("loaded_bags") or []:
            code = str(row.get("bag_code") or "")
            if code:
                used.add(code)
        for out in station.get("output_bags") or []:
            for code in out.get("input_bag_codes") or []:
                if code:
                    used.add(str(code))
        for code in used:
            dest = dest_map.get(code)
            if dest == key:
                busy.add(code)
            elif dest is None and not _is_destoning_bag_code(code):
                busy.add(code)
    return busy


def _bag_qc(bag: dict) -> dict:
    qc = bag.get("quality_qc") if isinstance(bag.get("quality_qc"), dict) else {}
    return qc


def _session_actor(user: Any) -> str | None:
    if user is None:
        return None
    raw = getattr(user, "username", None) or getattr(user, "email", None)
    text = str(raw or "").strip()
    return text or None


def _check_user_id(bag: dict) -> str | None:
    qc = _bag_qc(bag)
    user_id = str(qc.get("user_id") or bag.get("created_by") or "").strip()
    return user_id or None


def _destination_process(values: dict | None) -> str | None:
    return _values_destination(values)


def _routed_bags_for_process(stations: dict[str, dict], process_key: str, busy: set[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for source_key, station in stations.items():
        if source_key == process_key:
            continue
        for bag in station.get("output_bags") or []:
            code = str(bag.get("bag_code") or "")
            if not code or code in busy or code in seen:
                continue
            if not _bag_qc_saved(bag):
                continue
            dest = _normalize_destination_label(_bag_destination_raw(bag))
            if dest != process_key:
                continue
            seen.add(code)
            rows.append({**dict(bag), "source_process": source_key})
    return rows


def _find_loadable_bag(
    db: Session, tenant: TenantContext, stations: dict[str, dict], process_key: str, code: str
) -> dict | None:
    found = next(
        (bag for bag in _destoning_output_bags(db, tenant) if str(bag.get("bag_code") or "") == code),
        None,
    )
    if found is not None and _destoning_destination(found) == process_key:
        return found
    for bag in _routed_bags_for_process(stations, process_key, set()):
        if str(bag.get("bag_code") or "") == code:
            return bag
    return None


def _destoning_destination(bag: dict) -> str | None:
    from app.services.industry.activated_carbon import process_rules as ac_process_rules

    if _is_in_stock_destination(_bag_destination_raw(bag)):
        return None
    if not _bag_qc_saved(bag):
        return None
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
    dest = _values_destination(values)
    if dest == ac_process_rules.DESTONING_REWORK_PROCESS_KEY:
        return None
    if dest is not None:
        return dest
    labelled = _normalize_destination_label(
        str(bag.get("deston_qc_destination") or bag.get("destination") or "")
    )
    if labelled == ac_process_rules.DESTONING_REWORK_PROCESS_KEY:
        return None
    if labelled is not None:
        return labelled
    return None


def _destoning_bags_for_process(
    db: Session, tenant: TenantContext, process_key: str, busy: set[str]
) -> list[dict]:
    rows: list[dict] = []
    for bag in _destoning_output_bags(db, tenant):
        code = str(bag.get("bag_code") or "")
        if not code or code in busy:
            continue
        if _destoning_destination(bag) != process_key:
            continue
        rows.append(bag)
    return rows


def _destoning_grade(bag: dict) -> str | None:
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
    for key in ("deston_qc_grade", "grade", "deston_qc_destination"):
        value = values.get(key) or bag.get(key)
        if value:
            return str(value)
    return None


def _destoning_output_bags(db: Session, tenant: TenantContext) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for destoner in _list_destoner_resources(db, tenant):
        meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
        for bag in meta.get("destoning_output_bags") or []:
            if not isinstance(bag, dict) or not bag.get("bag_code"):
                continue
            code = str(bag.get("bag_code"))
            if code in seen:
                continue
            seen.add(code)
            rows.append(dict(bag))
    return rows


def _removed_finished_goods_bags(station: dict) -> list[dict]:
    """Bags left on the removed Finished Goods step. They are In Stock."""
    outputs = [row for row in (station.get("output_bags") or []) if isinstance(row, dict)]
    consumed = {
        str(code)
        for bag in outputs
        for code in (bag.get("input_bag_codes") or [])
        if code
    }
    loaded = [
        row
        for row in (station.get("loaded_bags") or [])
        if isinstance(row, dict) and str(row.get("bag_code") or "") not in consumed
    ]
    return outputs + loaded


def _bag_available_as_stock(bag: dict, station_key: str) -> bool:
    if station_key == "fg_qc":
        if bag.get("dispatched") or _bag_remaining_kg(bag) <= 0:
            return False
        return _normalize_destination_label(_bag_destination_raw(bag)) is None
    return bag_is_available_in_stock(bag)


def list_available_in_stock_bags(db: Session, tenant: TenantContext) -> list[dict]:
    """Bags whose Quality destination is In Stock and still have remaining KG."""
    rows: list[dict] = []
    seen: set[str] = set()
    for bag in _destoning_output_bags(db, tenant):
        if not bag_is_available_in_stock(bag):
            continue
        code = str(bag.get("bag_code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append(_in_stock_bag_row(bag, source="destoning"))
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    for key, station in _stations(meta).items():
        bags = _removed_finished_goods_bags(station) if key == "fg_qc" else (station.get("output_bags") or [])
        for bag in bags:
            if not isinstance(bag, dict) or not _bag_available_as_stock(bag, key):
                continue
            code = str(bag.get("bag_code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(_in_stock_bag_row(bag, source=key))
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows


def available_in_stock_kg(db: Session, tenant: TenantContext) -> Decimal:
    return sum(
        (Decimal(str(row.get("remaining_kg") or 0)) for row in list_available_in_stock_bags(db, tenant)),
        Decimal("0"),
    )


def _apply_dispatch_to_bag(bag: dict, take: Decimal) -> Decimal:
    remaining = _bag_remaining_kg(bag)
    used = min(remaining, Decimal(str(take)))
    if used <= 0:
        return Decimal("0")
    already = Decimal(str(bag.get("dispatched_kg") or 0))
    bag["dispatched_kg"] = str(already + used)
    if _bag_remaining_kg(bag) <= 0:
        bag["dispatched"] = True
        bag["dispatched_at"] = datetime.now(timezone.utc).isoformat()
    return used


def bag_matches_work_order(bag: dict | None, work_order_code: str | None) -> bool:
    wanted = str(work_order_code or "").strip()
    if not wanted:
        return True
    return _work_order_of(bag) == wanted


def consume_in_stock_bags(
    db: Session,
    tenant: TenantContext,
    quantity_kg: Decimal,
    *,
    bag_codes: set[str] | None = None,
    work_order_code: str | None = None,
) -> list[dict]:
    """FIFO-consume In Stock bags and persist remaining KG."""
    remaining = Decimal(str(quantity_kg))
    if remaining <= 0:
        return []

    repo = _repo(db, tenant)
    destoner = _ensure_destoner_resource(db, tenant)
    dest_meta = destoner.metadata_ if destoner is not None and isinstance(destoner.metadata_, dict) else {}
    dest_outputs = (
        [row for row in (dest_meta.get("destoning_output_bags") or []) if isinstance(row, dict)]
        if destoner is not None
        else []
    )
    resource = _ensure_post_activation_resource(db, tenant)
    post_meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(post_meta)

    candidates: list[tuple[str, dict]] = []
    for bag in dest_outputs:
        if bag_is_available_in_stock(bag):
            candidates.append(("destoning", bag))
    for key, station in stations.items():
        bags = _removed_finished_goods_bags(station) if key == "fg_qc" else (station.get("output_bags") or [])
        for bag in bags:
            if isinstance(bag, dict) and _bag_available_as_stock(bag, key):
                candidates.append((key, bag))
    candidates.sort(key=lambda item: str(item[1].get("created_at") or ""))

    consumed: list[dict] = []
    for source, bag in candidates:
        if remaining <= 0:
            break
        code = str(bag.get("bag_code") or "")
        if bag_codes is not None and code not in bag_codes:
            continue
        if not bag_matches_work_order(bag, work_order_code):
            continue
        used = _apply_dispatch_to_bag(bag, remaining)
        if used <= 0:
            continue
        remaining -= used
        consumed.append(
            {
                **_in_stock_bag_row(bag, source=source),
                "consumed_kg": used,
                "remaining_kg": _bag_remaining_kg(bag),
            }
        )

    if destoner is not None:
        destoner.metadata_ = {**dest_meta, "destoning_output_bags": dest_outputs}
        flag_modified(destoner, "metadata_")
    _write_stations(resource, post_meta, stations)
    repo.db.flush()
    return consumed


def _bag_out(
    row: dict,
    *,
    process: str | None = None,
    work_order_ctc: str | None = None,
) -> AcPostActivationBagOut:
    return AcPostActivationBagOut(
        bag_code=str(row.get("bag_code") or ""),
        quantity_kg=Decimal(str(row.get("quantity_kg") or 0)),
        grade=row.get("grade") or _destoning_grade(row),
        mesh=str(row.get("mesh") or "").strip() or None,
        lot_code=row.get("lot_code"),
        work_order_code=_work_order_of(row),
        work_order_ctc=work_order_ctc,
        created_at=row.get("created_at"),
        created_by=str(row.get("created_by") or "").strip() or None,
        loaded_at=row.get("loaded_at"),
        user_id=_check_user_id(row),
        input_bag_codes=[str(code) for code in (row.get("input_bag_codes") or []) if code],
        process=process,
    )


def _event_out(row: dict) -> AcPostActivationLoadEventOut:
    return AcPostActivationLoadEventOut(
        bag_code=row.get("bag_code"),
        lot_code=row.get("lot_code"),
        kg=Decimal(str(row.get("kg") or row.get("quantity_kg") or 0)),
        loaded_at=row.get("loaded_at") or row.get("created_at"),
        process=row.get("process"),
    )


def _write_stations(resource: Resource, meta: dict, stations: dict[str, dict]) -> None:
    resource.metadata_ = {**meta, "role": "post_activation", "stations": stations}
    flag_modified(resource, "metadata_")


def get_post_activation_state(
    db: Session, tenant: TenantContext, process: str, *, scope: str | None = None
) -> AcPostActivationStateOut:
    spec = resolve_post_activation_process(process)
    key = spec["key"]
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    dest_map = _destoning_dest_map(db, tenant)
    _reconcile_station_loads(stations, dest_map)
    station = stations[key]
    busy = _busy_bag_codes(stations, dest_map)
    ctc_cache: dict[str, str | None] = {}

    def bag_out(row: dict, process: str | None = None) -> AcPostActivationBagOut:
        return _bag_out(
            row,
            process=process,
            work_order_ctc=_lookup_work_order_ctc(db, tenant, _work_order_of(row), ctc_cache),
        )

    available_rows = _destoning_bags_for_process(db, tenant, key, busy)
    available_rows.extend(_routed_bags_for_process(stations, key, busy))
    loaded_rows = [row for row in station["loaded_bags"] if row.get("bag_code")]
    output_rows = [row for row in station["output_bags"] if row.get("bag_code")]
    active_code = active_post_work_order(loaded_rows, available_rows, output_rows)
    available_rows = rows_for_active_work_order(available_rows, active_code)
    output_rows = output_rows_for_scope(
        station["output_bags"],
        tz_name=getattr(tenant, "timezone", None),
        scope=scope,
    )
    available = [bag_out(bag, process=bag.get("source_process")) for bag in available_rows]
    loaded = [bag_out(row, process=key) for row in loaded_rows]
    outputs = [
        bag_out(row, process=key)
        for row in output_rows
    ]
    loaded_codes = {str(row.get("bag_code") or "") for row in loaded_rows}
    events = [
        event
        for event in (station["load_events"] or [])
        if str(event.get("bag_code") or "") in loaded_codes
    ]
    if not events:
        events = [
            {
                "bag_code": row.get("bag_code"),
                "lot_code": row.get("lot_code"),
                "kg": row.get("quantity_kg") or 0,
                "loaded_at": row.get("loaded_at") or row.get("created_at"),
                "process": key,
            }
            for row in loaded_rows
        ]
    loaded_kg = station_loaded_kg(station)
    output_kg = station_current_output_kg(station)
    remaining_kg = loaded_kg - output_kg
    if remaining_kg < 0:
        remaining_kg = Decimal("0")
    work_order_code = active_code
    return AcPostActivationStateOut(
        process=key,
        process_label=spec["label"],
        available=available,
        loaded=loaded,
        loaded_kg=loaded_kg,
        output_kg=output_kg,
        remaining_kg=remaining_kg,
        loader_count=len(loaded),
        loader_capacity=POST_ACTIVATION_LOADER_CAPACITY,
        monthly_capacity_kg=station_monthly_capacity_kg(db, tenant, key),
        work_order_code=work_order_code,
        work_order_ctc=_lookup_work_order_ctc(db, tenant, work_order_code, ctc_cache),
        selected_mesh=str(station.get("selected_mesh") or "").strip() or None,
        output_bags=outputs,
        load_events=[_event_out(row) for row in events if row.get("bag_code") or row.get("loaded_at")],
    )


def load_post_activation_bag(
    db: Session, tenant: TenantContext, process: str, payload: AcPostActivationLoadCreate
) -> AcPostActivationStateOut:
    spec = resolve_post_activation_process(process)
    key = spec["key"]
    repo = _repo(db, tenant)
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    dest_map = _destoning_dest_map(db, tenant)
    _reconcile_station_loads(stations, dest_map)
    _remove_bag_from_other_stations(stations, key, (payload.bag_code or "").strip())
    station = stations[key]
    code = (payload.bag_code or "").strip()
    if not code:
        raise ValidationError("Bag number is required.")
    if any(str(row.get("bag_code") or "") == code for row in station["loaded_bags"]):
        raise ValidationError(f"Bag '{code}' is already on {spec['label']}.")
    capacity = POST_ACTIVATION_LOADER_CAPACITY
    if len(station["loaded_bags"]) >= capacity:
        raise ValidationError(f"{spec['label']} loader is full ({capacity} bags).")
    if code in _busy_bag_codes(stations, dest_map):
        raise ValidationError(f"Bag '{code}' is already loaded on a post-activation process.")
    found = _find_loadable_bag(db, tenant, stations, key, code)
    if found is not None:
        active_code = next(
            (_work_order_of(row) for row in station["loaded_bags"] if _work_order_of(row)),
            None,
        )
        incoming = _work_order_of(found)
        if active_code and incoming != active_code:
            raise ValidationError(
                f"This loader is on work order {active_code}. "
                "Finish that work order before loading another."
            )
    if found is None:
        dest = dest_map.get(code)
        if dest and dest != key:
            raise ValidationError(
                f"Bag '{code}' is routed to {POST_ACTIVATION_PROCESSES[dest]['label']} "
                "by Destoning Quality destination."
            )
        raise ValidationError(
            f"Bag '{code}' is not available for {spec['label']}. "
            "Set Quality destination to this process first."
        )
    mesh_code = None
    if key == "screening":
        from app.services.industry.activated_carbon.mesh_grade import (
            get_mesh_grade_map,
            resolve_mesh_code,
        )

        catalog = get_mesh_grade_map(db, tenant)
        resolved = resolve_mesh_code(catalog, payload.mesh)
        mesh_code = screening_mesh_for_load(station, resolved or "")
        station["selected_mesh"] = mesh_code
    now = datetime.now(timezone.utc).isoformat()
    station["loaded_bags"].append(
        {
            "bag_code": code,
            "quantity_kg": float(found.get("quantity_kg") or 0),
            "grade": found.get("grade") or _destoning_grade(found),
            "mesh": mesh_code,
            "lot_code": found.get("lot_code"),
            "work_order_code": _work_order_of(found),
            "created_at": found.get("created_at"),
            "loaded_at": now,
        }
    )
    station["load_events"].append(
        {
            "bag_code": code,
            "lot_code": found.get("lot_code"),
            "kg": float(found.get("quantity_kg") or 0),
            "loaded_at": now,
            "process": key,
        }
    )
    _write_stations(resource, meta, stations)
    repo.db.commit()
    return get_post_activation_state(db, tenant, key)


def unload_post_activation_bag(
    db: Session, tenant: TenantContext, process: str, payload: AcPostActivationLoadCreate
) -> AcPostActivationStateOut:
    spec = resolve_post_activation_process(process)
    key = spec["key"]
    repo = _repo(db, tenant)
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    dest_map = _destoning_dest_map(db, tenant)
    _reconcile_station_loads(stations, dest_map)
    station = stations[key]
    code = (payload.bag_code or "").strip()
    next_loaded = [row for row in station["loaded_bags"] if str(row.get("bag_code") or "") != code]
    if len(next_loaded) == len(station["loaded_bags"]):
        raise ValidationError(f"Bag '{code}' is not on {spec['label']}.")
    events = list(station["load_events"])
    for index in range(len(events) - 1, -1, -1):
        if str(events[index].get("bag_code") or "") == code:
            events.pop(index)
            break
    station["loaded_bags"] = next_loaded
    station["load_events"] = events
    if key == "screening" and not next_loaded:
        station["selected_mesh"] = None
    _write_stations(resource, meta, stations)
    repo.db.commit()
    return get_post_activation_state(db, tenant, key)


def create_post_activation_output_bag(
    db: Session,
    tenant: TenantContext,
    process: str,
    payload: AcPostActivationOutputCreate,
    user: Any = None,
) -> AcPostActivationStateOut:
    from app.services.industry.activated_carbon import triplet_capture as ac_triples

    spec = resolve_post_activation_process(process)
    key = spec["key"]
    repo = _repo(db, tenant)
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    dest_map = _destoning_dest_map(db, tenant)
    _reconcile_station_loads(stations, dest_map)
    station = stations[key]
    if not station["loaded_bags"]:
        raise ValidationError(f"Load a destoning bag onto {spec['label']} first.")
    assert_output_within_loaded(station, payload.quantity_kg, spec["label"])
    grade = (payload.grade or "").strip()
    if key in EXKLIN_ONLY_PROCESSES:
        grade = EXKLIN_GRADE
    if not grade:
        if key == "screening_after_destoning":
            grade = "Ungraded"
        else:
            raise ValidationError("Grade is required for the output bag.")
    mesh_code = None
    if key == "screening":
        from app.services.industry.activated_carbon.mesh_grade import (
            get_mesh_grade_map,
            grades_for_mesh,
            resolve_mesh_code,
        )

        mesh_raw = (payload.mesh or "").strip()
        if not mesh_raw:
            raise ValidationError("Choose a mesh configuration, then enter the grade for that mesh.")
        catalog = get_mesh_grade_map(db, tenant)
        mesh_code = resolve_mesh_code(catalog, mesh_raw)
        active = str(station.get("selected_mesh") or "").strip().upper()
        if active and mesh_code and mesh_code.upper() != active:
            raise ValidationError(
                f"Bags were loaded on mesh {active}. Tag grades for that mesh."
            )
        allowed = grades_for_mesh(db, tenant, mesh_code)
        if not _grade_on_mesh(grade, allowed):
            raise ValidationError(
                f"Grade '{grade}' is not on mesh {mesh_code}. Choose a grade from that mesh."
            )
    bag_code = next_post_activation_bag_code(repo.db, spec["prefix"], tenant.timezone)
    now = datetime.now(timezone.utc).isoformat()
    load_times = [
        str(row.get("loaded_at"))
        for row in station["loaded_bags"]
        if row.get("loaded_at")
    ]
    loaded_at = min(load_times) if load_times else None
    input_codes = [str(row.get("bag_code")) for row in station["loaded_bags"] if row.get("bag_code")]
    lot_code = (payload.lot_code or "").strip() or next(
        (str(row.get("lot_code")) for row in station["loaded_bags"] if row.get("lot_code")),
        None,
    )
    work_order_code = next(
        (_work_order_of(row) for row in station["loaded_bags"] if _work_order_of(row)),
        None,
    )
    station["output_bags"].append(
        {
            "bag_code": bag_code,
            "quantity_kg": float(payload.quantity_kg),
            "grade": grade,
            "mesh": mesh_code,
            "lot_code": lot_code,
            "work_order_code": work_order_code,
            "created_at": now,
            "created_by": _session_actor(user),
            "loaded_at": loaded_at,
            "input_bag_codes": input_codes,
        }
    )
    if key not in {"screening", "crushing"}:
        station["loaded_bags"] = []
    _write_stations(resource, meta, stations)
    subject = f"urn:nyra:ac:{spec['bag_kind']}:{bag_code}"
    ac_triples.stage_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:contained_in",
            object_uri=f"urn:nyra:ac:postActivation:{resource.resource_code}:{key}",
            source_table="cfg.resource",
            source_id=resource.resource_id,
        ),
    )
    for src in input_codes:
        ac_triples.stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:generatedFrom",
                object_uri=f"urn:nyra:ac:destonBag:{src}",
                source_table="cfg.resource",
                source_id=resource.resource_id,
            ),
        )
    values: dict[str, Any] = {
        f"{key}_bag_ref": bag_code,
        f"{key}_output_kg": str(payload.quantity_kg),
        f"{key}_grade": grade,
        f"{key}_input_bag_ref": ",".join(input_codes),
    }
    if mesh_code:
        values[f"{key}_mesh"] = mesh_code
    ac_triples.stage_captures_for_values(
        db,
        tenant,
        subject_uri=subject,
        values=values,
        source_table="cfg.resource",
        source_id=resource.resource_id,
        param_defs=[],
        process_step=spec["process_step"],
        used_at="execution",
        operation_code=spec["operation_code"],
        flush_only=True,
    )
    if work_order_code:
        ac_triples.stage_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:assignedTo",
                object_uri=f"urn:nyra:ac:workOrder:{work_order_code}",
                source_table="cfg.resource",
                source_id=resource.resource_id,
            ),
        )
    if lot_code:
        ac_triples.stage_captures_for_values(
            db,
            tenant,
            subject_uri=f"urn:nyra:ac:lot:{lot_code}",
            values=values,
            source_table="cfg.resource",
            source_id=resource.resource_id,
            param_defs=[],
            process_step=spec["process_step"],
            used_at="execution",
            operation_code=spec["operation_code"],
            flush_only=True,
        )
    repo.db.commit()
    return get_post_activation_state(db, tenant, key)


def list_post_activation_quality(
    db: Session, tenant: TenantContext, *, scope: str | None = None
) -> AcPostActivationQualityOut:
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    sections: list[AcPostActivationQualitySectionOut] = []
    ctc_cache: dict[str, str | None] = {}
    for key in QUALITY_SECTION_KEYS:
        spec = POST_ACTIVATION_PROCESSES[key]
        station = stations[key]
        output_rows = list(
            reversed(
                output_rows_for_scope(
                    station["output_bags"],
                    tz_name=getattr(tenant, "timezone", None),
                    scope=scope,
                )
            )
        )
        bags: list[AcPostActivationQualityBagOut] = []
        for bag in output_rows:
            code = str(bag.get("bag_code") or "")
            if not code:
                continue
            qc = _bag_qc(bag)
            values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
            wo_code = _work_order_of(bag)
            bags.append(
                AcPostActivationQualityBagOut(
                    bag_code=code,
                    quantity_kg=Decimal(str(bag.get("quantity_kg") or 0)),
                    grade=bag.get("grade"),
                    mesh=str(bag.get("mesh") or "").strip() or None,
                    lot_code=bag.get("lot_code"),
                    work_order_code=wo_code,
                    work_order_ctc=_lookup_work_order_ctc(db, tenant, wo_code, ctc_cache),
                    created_at=bag.get("created_at"),
                    user_id=qc.get("user_id"),
                    process=key,
                    values=values,
                    saved_at=qc.get("saved_at"),
                )
            )
        sections.append(
            AcPostActivationQualitySectionOut(
                process=key,
                process_label=QUALITY_SECTION_LABELS.get(key, spec["label"]),
                bags=bags,
            )
        )
    return AcPostActivationQualityOut(sections=sections)


def save_post_activation_quality(
    db: Session, tenant: TenantContext, payload: AcPostActivationQualitySave
) -> AcPostActivationQualityBagOut:
    from app.services.industry.activated_carbon import triplet_capture as ac_triples

    spec = resolve_post_activation_process(payload.process)
    if spec["key"] not in QUALITY_SECTION_KEYS:
        raise ValidationError(f"Quality is not captured on {spec['label']}.")
    repo = _repo(db, tenant)
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    station = stations[spec["key"]]
    code = (payload.bag_code or "").strip()
    found = next((bag for bag in station["output_bags"] if str(bag.get("bag_code") or "") == code), None)
    if found is None:
        raise ValidationError(f"Bag '{code}' was not found on {spec['label']}.")
    existing = _bag_qc(found)
    if existing.get("saved_at"):
        raise ValidationError(f"Quality for bag '{code}' is already saved and cannot be changed.")
    values: dict[str, Any] = {}
    for key, raw in (payload.values or {}).items():
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        values[str(key)] = text
    wo_ctc = _lookup_work_order_ctc(db, tenant, _work_order_of(found))
    if wo_ctc:
        values["post_qc_ctc"] = wo_ctc
    now = datetime.now(timezone.utc).isoformat()
    found["quality_qc"] = {
        "values": values,
        "user_id": (payload.user_id or "").strip() or None,
        "saved_at": now,
    }
    dest_raw = _values_destination_raw(values)
    if dest_raw:
        found["post_qc_destination"] = dest_raw
    _write_stations(resource, meta, stations)
    ac_triples.stage_captures_for_values(
        db,
        tenant,
        subject_uri=f"urn:nyra:ac:{spec['bag_kind']}:{code}",
        values=values,
        source_table="cfg.resource",
        source_id=resource.resource_id,
        param_defs=[],
        process_step=spec["process_step"],
        used_at="execution",
        operation_code=spec["operation_code"],
    )
    repo.db.commit()
    return AcPostActivationQualityBagOut(
        bag_code=code,
        quantity_kg=Decimal(str(found.get("quantity_kg") or 0)),
        grade=found.get("grade"),
        mesh=str(found.get("mesh") or "").strip() or None,
        lot_code=found.get("lot_code"),
        work_order_code=_work_order_of(found),
        work_order_ctc=wo_ctc,
        created_at=found.get("created_at"),
        user_id=_check_user_id(found),
        process=spec["key"],
        values=values,
        saved_at=now,
    )


def reassign_in_stock_work_order(
    db: Session,
    tenant: TenantContext,
    *,
    bag_code: str,
    work_order_code: str,
    user_id: str | None = None,
) -> dict[str, str | None]:
    """Move an In Stock bag onto another work order of the same grade.

    The previous assignment stays on the bag and as an assignedTo triple.
    Subjects and predicates are unchanged.
    """
    from app.schemas.mes_core.schemas import TripleCreate
    from app.services.industry.activated_carbon import inbound_admin, triplet_capture as ac_triples
    from app.services.industry.activated_carbon import work_orders as ac_work_orders

    wanted = (bag_code or "").strip()
    target_code = (work_order_code or "").strip()
    if not wanted or not target_code:
        raise ValidationError("Choose an in-stock bag and a work order.")
    target = ac_work_orders.get_work_order(db, tenant, target_code)
    found: dict | None = None
    subject = ""
    holder = None
    holder_meta: dict = {}
    stations = None

    for destoner in _list_destoner_resources(db, tenant):
        meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
        for bag in meta.get("destoning_output_bags") or []:
            if isinstance(bag, dict) and str(bag.get("bag_code") or "") == wanted:
                if not bag_is_available_in_stock(bag):
                    raise ValidationError(f"Bag {wanted} is not in stock.")
                found = bag
                subject = f"urn:nyra:ac:destonBag:{wanted}"
                holder = destoner
                holder_meta = meta
                break
        if found is not None:
            break

    resource = _ensure_post_activation_resource(db, tenant)
    post_meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    if found is None:
        stations = _stations(post_meta)
        for key, station in stations.items():
            bags = (
                _removed_finished_goods_bags(station)
                if key == "fg_qc"
                else (station.get("output_bags") or [])
            )
            spec = POST_ACTIVATION_PROCESSES.get(key) or {}
            for bag in bags:
                if not isinstance(bag, dict) or str(bag.get("bag_code") or "") != wanted:
                    continue
                if not _bag_available_as_stock(bag, key):
                    raise ValidationError(f"Bag {wanted} is not in stock.")
                found = bag
                kind = spec.get("bag_kind") or "screenBag"
                subject = f"urn:nyra:ac:{kind}:{wanted}"
                holder = resource
                holder_meta = post_meta
                break
            if found is not None:
                break

    if found is None or holder is None:
        raise ValidationError(f"Bag '{wanted}' is not in stock.")

    current = _work_order_of(found)
    if not current:
        raise ValidationError(f"Bag {wanted} has no work order to move.")
    if current == target_code:
        raise ValidationError(f"Bag {wanted} is already on {target_code}.")
    source = ac_work_orders.get_work_order(db, tenant, current)
    source_grade = inbound_admin._canonical_outward_grade(str(source.get("grade") or ""))
    target_grade = inbound_admin._canonical_outward_grade(str(target.get("grade") or ""))
    if not source_grade or source_grade != target_grade:
        raise ValidationError(
            f"Work order {target_code} is grade {target.get('grade') or '—'}. "
            f"{current} is grade {source.get('grade') or '—'}. "
            "Move stock only when the grade matches."
        )

    history = [row for row in (found.get("work_order_history") or []) if isinstance(row, dict)]
    history.append(
        {
            "from_work_order_code": current,
            "to_work_order_code": target_code,
            "at": datetime.now(timezone.utc).isoformat(),
            "by": (user_id or "").strip() or None,
        }
    )
    found["work_order_history"] = history
    found["work_order_code"] = target_code
    if holder is resource and stations is not None:
        _write_stations(resource, post_meta, stations)
    else:
        outputs = [
            row
            for row in (holder_meta.get("destoning_output_bags") or [])
            if isinstance(row, dict)
        ]
        holder.metadata_ = {**holder_meta, "destoning_output_bags": outputs}
        flag_modified(holder, "metadata_")

    ac_triples.stage_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:assignedTo",
            object_uri=f"urn:nyra:ac:workOrder:{target_code}",
            source_table="cfg.resource",
            source_id=holder.resource_id,
        ),
    )
    _repo(db, tenant).db.commit()
    return {
        "bag_code": wanted,
        "work_order_code": target_code,
        "previous_work_order_code": current,
        "grade": source_grade,
    }
