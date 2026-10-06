"""Shared live-load for post-activation shop steps.

Destoning output bags can be loaded on screening, crushing, de-dusting,
de-magnetisation, blending, or finished-goods. A bag loaded or consumed on
any of those stations is hidden from every other loader.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
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
from app.services.industry.activated_carbon.codes import next_post_activation_bag_code
from app.services.mes_core.base import TenantRepository
from app.services.industry.activated_carbon.station_machines import station_machine_capacity

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
    "screening": "screening",
    "crushing": "crushing",
    "de-dusting": "dedusting",
    "dedusting": "dedusting",
    "de-magnetize": "demagnetisation",
    "de-magnetise": "demagnetisation",
    "demagnetisation": "demagnetisation",
    "blending": "blending",
    "finished goods": "fg_qc",
    "finished-goods": "fg_qc",
    "fg": "fg_qc",
}

POST_ACTIVATION_PROCESSES = {
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
    "fg_qc": {
        "label": "Finished Goods",
        "prefix": "FG",
        "operation_code": "OP-FG-QC",
        "process_step": "QC",
        "bag_kind": "fgBag",
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
    for resource in _tenant_resources(db, tenant).all():
        code = (resource.resource_code or "").upper()
        name = (resource.resource_name or "").upper()
        meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
        role = str(meta.get("role") or "").lower()
        if "DESTON" in code or "DESTON" in name or role == "destoning":
            return resource
    return None


def _stations(meta: dict) -> dict[str, dict]:
    raw = meta.get("stations") if isinstance(meta.get("stations"), dict) else {}
    stations: dict[str, dict] = {}
    for key in POST_ACTIVATION_PROCESSES:
        row = raw.get(key) if isinstance(raw.get(key), dict) else {}
        stations[key] = {
            "loaded_bags": [dict(item) for item in (row.get("loaded_bags") or []) if isinstance(item, dict)],
            "output_bags": [dict(item) for item in (row.get("output_bags") or []) if isinstance(item, dict)],
            "load_events": [dict(item) for item in (row.get("load_events") or []) if isinstance(item, dict)],
        }
    return stations


def _is_in_stock_destination(raw: str | None) -> bool:
    text = re.sub(r"[^a-z0-9]+", " ", str(raw or "").strip().lower()).strip()
    return text in {"in stock", "instock"}


def _normalize_destination_label(raw: str | None) -> str | None:
    text = re.sub(r"[^a-z0-9]+", " ", str(raw or "").strip().lower()).strip()
    if not text or text in {"in stock", "instock"}:
        return None
    aliases = {
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
        "finished goods": "fg_qc",
        "finished goods qc": "fg_qc",
        "fg": "fg_qc",
        "fg qc": "fg_qc",
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


def _destination_process(values: dict | None) -> str | None:
    return _values_destination(values)


def _routed_bags_for_process(stations: dict[str, dict], process_key: str, busy: set[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for source_key, station in stations.items():
        for bag in station.get("output_bags") or []:
            code = str(bag.get("bag_code") or "")
            if not code or code in busy or code in seen:
                continue
            dest = _destination_process(_bag_qc(bag).get("values") if isinstance(_bag_qc(bag).get("values"), dict) else {})
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
    qc = bag.get("destoning_qc") if isinstance(bag.get("destoning_qc"), dict) else {}
    values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
    dest = _values_destination(values)
    if dest is not None:
        return dest
    return _normalize_destination_label(str(bag.get("deston_qc_destination") or bag.get("destination") or ""))


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
    destoner = _ensure_destoner_resource(db, tenant)
    if destoner is None:
        return []
    meta = destoner.metadata_ if isinstance(destoner.metadata_, dict) else {}
    rows = []
    for bag in meta.get("destoning_output_bags") or []:
        if not isinstance(bag, dict) or not bag.get("bag_code"):
            continue
        rows.append(dict(bag))
    return rows


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
        for bag in station.get("output_bags") or []:
            if not isinstance(bag, dict) or not bag_is_available_in_stock(bag):
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


def consume_in_stock_bags(
    db: Session,
    tenant: TenantContext,
    quantity_kg: Decimal,
    *,
    bag_codes: set[str] | None = None,
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
        for bag in station.get("output_bags") or []:
            if isinstance(bag, dict) and bag_is_available_in_stock(bag):
                candidates.append((key, bag))
    candidates.sort(key=lambda item: str(item[1].get("created_at") or ""))

    consumed: list[dict] = []
    for source, bag in candidates:
        if remaining <= 0:
            break
        code = str(bag.get("bag_code") or "")
        if bag_codes is not None and code not in bag_codes:
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


def _bag_out(row: dict, *, process: str | None = None) -> AcPostActivationBagOut:
    return AcPostActivationBagOut(
        bag_code=str(row.get("bag_code") or ""),
        quantity_kg=Decimal(str(row.get("quantity_kg") or 0)),
        grade=row.get("grade") or _destoning_grade(row),
        lot_code=row.get("lot_code"),
        created_at=row.get("created_at"),
        loaded_at=row.get("loaded_at"),
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
    db: Session, tenant: TenantContext, process: str
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
    available = [
        _bag_out(bag)
        for bag in _destoning_bags_for_process(db, tenant, key, busy)
    ]
    available.extend(
        _bag_out(bag, process=bag.get("source_process"))
        for bag in _routed_bags_for_process(stations, key, busy)
    )
    loaded = [_bag_out(row, process=key) for row in station["loaded_bags"] if row.get("bag_code")]
    outputs = [_bag_out(row, process=key) for row in station["output_bags"] if row.get("bag_code")]
    events = station["load_events"]
    if not events:
        events = [
            {
                "bag_code": row.get("bag_code"),
                "lot_code": row.get("lot_code"),
                "kg": row.get("quantity_kg") or 0,
                "loaded_at": row.get("loaded_at") or row.get("created_at"),
                "process": key,
            }
            for row in station["loaded_bags"]
            if row.get("bag_code")
        ]
    loaded_kg = sum((Decimal(str(row.quantity_kg or 0)) for row in loaded), Decimal("0"))
    return AcPostActivationStateOut(
        process=key,
        process_label=spec["label"],
        available=available,
        loaded=loaded,
        loaded_kg=loaded_kg,
        loader_count=len(loaded),
        loader_capacity=station_machine_capacity(db, tenant, key),
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
    capacity = station_machine_capacity(db, tenant, key)
    if len(station["loaded_bags"]) >= capacity:
        raise ValidationError(f"{spec['label']} is full ({capacity} machines).")
    if code in _busy_bag_codes(stations, dest_map):
        raise ValidationError(f"Bag '{code}' is already loaded on a post-activation process.")
    found = _find_loadable_bag(db, tenant, stations, key, code)
    if found is None:
        dest = dest_map.get(code)
        if dest and dest != key:
            raise ValidationError(
                f"Bag '{code}' is routed to {POST_ACTIVATION_PROCESSES[dest]['label']} "
                "by Destoning Quality destination."
            )
        raise ValidationError(
            f"Bag '{code}' is not available for {spec['label']}. "
            "Set Destoning Quality destination to this process first."
        )
    now = datetime.now(timezone.utc).isoformat()
    station["loaded_bags"].append(
        {
            "bag_code": code,
            "quantity_kg": float(found.get("quantity_kg") or 0),
            "grade": found.get("grade") or _destoning_grade(found),
            "lot_code": found.get("lot_code"),
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
    _write_stations(resource, meta, stations)
    repo.db.commit()
    return get_post_activation_state(db, tenant, key)


def create_post_activation_output_bag(
    db: Session, tenant: TenantContext, process: str, payload: AcPostActivationOutputCreate
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
    grade = (payload.grade or "").strip()
    if key in EXKLIN_ONLY_PROCESSES:
        grade = EXKLIN_GRADE
    if not grade:
        raise ValidationError("Grade is required for the output bag.")
    bag_code = next_post_activation_bag_code(repo.db, spec["prefix"])
    now = datetime.now(timezone.utc).isoformat()
    input_codes = [str(row.get("bag_code")) for row in station["loaded_bags"] if row.get("bag_code")]
    lot_code = (payload.lot_code or "").strip() or next(
        (str(row.get("lot_code")) for row in station["loaded_bags"] if row.get("lot_code")),
        None,
    )
    station["output_bags"].append(
        {
            "bag_code": bag_code,
            "quantity_kg": float(payload.quantity_kg),
            "grade": grade,
            "lot_code": lot_code,
            "created_at": now,
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


def list_post_activation_quality(db: Session, tenant: TenantContext) -> AcPostActivationQualityOut:
    resource = _ensure_post_activation_resource(db, tenant)
    meta = resource.metadata_ if isinstance(resource.metadata_, dict) else {}
    stations = _stations(meta)
    sections: list[AcPostActivationQualitySectionOut] = []
    for key in QUALITY_SECTION_KEYS:
        spec = POST_ACTIVATION_PROCESSES[key]
        bags: list[AcPostActivationQualityBagOut] = []
        for bag in reversed(stations[key]["output_bags"]):
            code = str(bag.get("bag_code") or "")
            if not code:
                continue
            qc = _bag_qc(bag)
            values = qc.get("values") if isinstance(qc.get("values"), dict) else {}
            bags.append(
                AcPostActivationQualityBagOut(
                    bag_code=code,
                    quantity_kg=Decimal(str(bag.get("quantity_kg") or 0)),
                    grade=bag.get("grade"),
                    lot_code=bag.get("lot_code"),
                    created_at=bag.get("created_at"),
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
    now = datetime.now(timezone.utc).isoformat()
    found["quality_qc"] = {
        "values": values,
        "user_id": (payload.user_id or "").strip() or None,
        "saved_at": now,
    }
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
        lot_code=found.get("lot_code"),
        created_at=found.get("created_at"),
        process=spec["key"],
        values=values,
        saved_at=now,
    )
