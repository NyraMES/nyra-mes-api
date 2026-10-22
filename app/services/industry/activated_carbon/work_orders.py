"""Activation work orders — grade, CTC, and quantity. Not customer POs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import Tenant
from app.services.industry.activated_carbon import inbound_admin as ac_inbound_admin
from app.services.industry.activated_carbon import inbound_workflow as ac_inbound_workflow
from app.services.industry.activated_carbon import process_rules as ac_process_rules
from app.services.industry.activated_carbon.codes import generate_ac_business_code

META_KEY = "ac_activation_work_orders"


def _tenant_row(db: Session, tenant: TenantContext) -> Tenant:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        raise ValidationError("Plant tenant was not found.")
    return row


def kiln_feed_grade_options(db: Session, tenant: TenantContext) -> list[str]:
    labels = ac_inbound_admin.outward_grade_labels(db, tenant)
    return [label for label in labels if ac_inbound_workflow._is_kiln_feed_grade(label)]


def _as_kg(raw: Any) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Work order quantity must be a number of KG.")
    if value <= 0:
        raise ValidationError("Work order quantity must be greater than zero.")
    return value


def _row_kg(row: dict | None, key: str = "kg") -> Decimal:
    if not isinstance(row, dict):
        return Decimal("0")
    raw = row.get(key)
    if raw in (None, ""):
        raw = row.get("kg")
    if raw in (None, ""):
        raw = row.get("quantity_kg")
    if raw in (None, ""):
        raw = row.get("weight_kg")
    try:
        return Decimal(str(raw or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def kiln_current_work_order_code(kiln_meta: dict | None) -> str | None:
    meta = kiln_meta if isinstance(kiln_meta, dict) else {}
    events = meta.get("kiln_feed_events")
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            code = str(event.get("work_order_code") or "").strip()
            if code:
                return code
    stored = str(meta.get("current_work_order_code") or "").strip()
    return stored or None


def kiln_feed_kg_for_work_order(kiln_meta: dict | None, work_order_code: str) -> Decimal:
    wanted = (work_order_code or "").strip()
    meta = kiln_meta if isinstance(kiln_meta, dict) else {}
    total = Decimal("0")
    for event in meta.get("kiln_feed_events") or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("work_order_code") or "").strip() != wanted:
            continue
        total += _row_kg(event)
    return total


def kiln_output_kg_for_work_order(kiln_meta: dict | None, work_order_code: str) -> Decimal:
    wanted = (work_order_code or "").strip()
    meta = kiln_meta if isinstance(kiln_meta, dict) else {}
    total = Decimal("0")
    for bag in meta.get("kiln_output_bags") or []:
        if not isinstance(bag, dict):
            continue
        if str(bag.get("work_order_code") or "").strip() != wanted:
            continue
        total += _row_kg(bag, "quantity_kg")
    return total


def kiln_total_feed_kg(kiln_meta: dict | None) -> Decimal:
    meta = kiln_meta if isinstance(kiln_meta, dict) else {}
    total = Decimal("0")
    for event in meta.get("kiln_feed_events") or []:
        if isinstance(event, dict):
            total += _row_kg(event)
    return total


def kiln_total_output_kg(kiln_meta: dict | None) -> Decimal:
    meta = kiln_meta if isinstance(kiln_meta, dict) else {}
    total = Decimal("0")
    for bag in meta.get("kiln_output_bags") or []:
        if isinstance(bag, dict):
            total += _row_kg(bag, "quantity_kg")
    return total


def kiln_remaining_output_kg(kiln_meta: dict | None) -> Decimal:
    remaining = kiln_total_feed_kg(kiln_meta) - kiln_total_output_kg(kiln_meta)
    return remaining if remaining > 0 else Decimal("0")


def work_order_kiln_output_done(
    quantity_kg: Any, output_kg: Any, status: str | None = None
) -> bool:
    """Kiln output is finished once the outputted kilograms cover the work order."""
    if str(status or "").strip().upper() == "FULFILLED":
        return True
    try:
        qty = Decimal(str(quantity_kg or 0))
        outputted = Decimal(str(output_kg or 0))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return qty > 0 and outputted + Decimal("0.001") >= qty


def kiln_output_kg_by_work_order(db: Session, tenant: TenantContext) -> dict[str, Decimal]:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    totals: dict[str, Decimal] = {}
    for row in ac_plant_equipment.ensure_six_kilns(db, tenant):
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        for bag in meta.get("kiln_output_bags") or []:
            if not isinstance(bag, dict):
                continue
            code = str(bag.get("work_order_code") or "").strip()
            if not code:
                continue
            totals[code] = totals.get(code, Decimal("0")) + _row_kg(bag, "quantity_kg")
    return totals


def work_order_output_kg_across_kilns(
    db: Session, tenant: TenantContext, work_order_code: str
) -> Decimal:
    from app.services.industry.activated_carbon import plant_equipment as ac_plant_equipment

    total = Decimal("0")
    for row in ac_plant_equipment.ensure_six_kilns(db, tenant):
        meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
        total += kiln_output_kg_for_work_order(meta, work_order_code)
    return total


def pending_dispatch_kg(quantity_kg: Any, dispatched_kg: Any) -> Decimal:
    ordered = Decimal(str(quantity_kg or 0))
    dispatched = Decimal(str(dispatched_kg or 0))
    return max(ordered - dispatched, Decimal("0"))


def _as_output_qty(quantity_kg: Any) -> Decimal:
    try:
        qty = Decimal(str(quantity_kg))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Kiln output weight must be a number of KG.")
    if qty <= 0:
        raise ValidationError("Kiln output weight must be greater than zero.")
    return qty


def assert_kiln_output_within_load(kiln_meta: dict | None, quantity_kg: Any) -> None:
    feed = kiln_total_feed_kg(kiln_meta)
    if feed <= 0:
        raise ValidationError(
            "No kiln feed is loaded. Load bags on Kiln Feed before adding output."
        )
    qty = _as_output_qty(quantity_kg)
    remaining = kiln_remaining_output_kg(kiln_meta)
    if qty > remaining + Decimal("0.001"):
        raise ValidationError(
            f"Output cannot exceed what is still in the kiln ({remaining} KG). "
            f"Fed {feed} KG so far."
        )


def assert_work_order_output_within_load(
    db: Session,
    tenant: TenantContext,
    work_order_code: str,
    quantity_kg: Any,
) -> None:
    work_order = get_work_order(db, tenant, work_order_code)
    loaded = Decimal(str(work_order.get("loaded_kg") or 0))
    if loaded <= 0:
        raise ValidationError(
            "No kiln feed is loaded. Load bags on Kiln Feed before adding output."
        )
    qty = _as_output_qty(quantity_kg)
    already = work_order_output_kg_across_kilns(db, tenant, work_order_code)
    remaining = loaded - already
    if remaining < 0:
        remaining = Decimal("0")
    if qty > remaining + Decimal("0.001"):
        raise ValidationError(
            f"Output cannot exceed what is still in the kiln ({remaining} KG). "
            f"Fed {loaded} KG so far."
        )


def kiln_open_work_order_codes(kiln_meta: dict | None) -> list[str]:
    """Work orders still occupying the kiln: feed kg exceeds output kg."""
    meta = kiln_meta if isinstance(kiln_meta, dict) else {}
    seen: list[str] = []
    for event in meta.get("kiln_feed_events") or []:
        if not isinstance(event, dict):
            continue
        code = str(event.get("work_order_code") or "").strip()
        if code and code not in seen:
            seen.append(code)
    current = str(meta.get("current_work_order_code") or "").strip()
    if current and current not in seen:
        seen.append(current)
    open_codes: list[str] = []
    for code in seen:
        feed = kiln_feed_kg_for_work_order(meta, code)
        output = kiln_output_kg_for_work_order(meta, code)
        if feed > output + Decimal("0.001"):
            open_codes.append(code)
    return open_codes


def kiln_open_work_order_code(kiln_meta: dict | None) -> str | None:
    """Latest work order still occupying the kiln: feed kg exceeds output kg."""
    open_codes = kiln_open_work_order_codes(kiln_meta)
    return open_codes[-1] if open_codes else None


def kiln_output_target_work_order(kiln_meta: dict | None, quantity_kg: Any) -> str | None:
    """Work order that should own the next kiln output bag.

    Same-grade work orders can share a kiln. Prefer the earliest open one that
    can still take this weight. If the weight is larger than any single open
    order, use the open order with the most feed still in the kiln.
    """
    qty = _as_output_qty(quantity_kg)
    open_codes = kiln_open_work_order_codes(kiln_meta)
    best: str | None = None
    best_remain = Decimal("-1")
    for code in open_codes:
        remain = kiln_feed_kg_for_work_order(kiln_meta, code) - kiln_output_kg_for_work_order(
            kiln_meta, code
        )
        if remain < 0:
            remain = Decimal("0")
        if remain + Decimal("0.001") >= qty:
            return code
        if remain > best_remain:
            best = code
            best_remain = remain
    if best:
        return best
    return kiln_current_work_order_code(kiln_meta)


def _work_order_ctc_key(row: dict | None) -> str | None:
    if not isinstance(row, dict):
        return None
    ctc = ac_process_rules.round_ctc(row.get("ctc"))
    if ctc is None:
        return None
    return str(ctc)


def assert_kiln_accepts_work_order(
    kiln_meta: dict | None,
    work_order_code: str,
    *,
    incoming: dict | None = None,
    lookup=None,
) -> None:
    """Allow another WO on the same kiln when CTC matches. Grade is not checked."""
    wanted = (work_order_code or "").strip()
    open_codes = kiln_open_work_order_codes(kiln_meta)
    if not open_codes or wanted in open_codes:
        return
    incoming_row = incoming
    if incoming_row is None and callable(lookup):
        incoming_row = lookup(wanted)
    incoming_ctc = _work_order_ctc_key(incoming_row)

    def _open_row(code: str) -> dict | None:
        if callable(lookup):
            try:
                return lookup(code)
            except ValidationError:
                return None
        return None

    for code in open_codes:
        open_row = _open_row(code)
        open_ctc = _work_order_ctc_key(open_row)
        if incoming_ctc and open_ctc and incoming_ctc == open_ctc:
            continue
        ctc = (open_row or {}).get("ctc") or "—"
        raise ValidationError(
            f"Kiln is running work order {code} (CTC {ctc}). "
            f"Load {wanted} only when it has the same CTC."
        )


def work_order_ctc_matches(work_order_ctc: Any, actual_ctc: Any) -> bool:
    target = ac_process_rules.round_ctc(work_order_ctc)
    actual = ac_process_rules.round_ctc(actual_ctc)
    return target is not None and actual is not None and target == actual


def _row_out(row: dict) -> dict[str, Any]:
    loaded = Decimal(str(row.get("loaded_kg") or 0))
    fulfilled = Decimal(str(row.get("fulfilled_kg") or 0))
    qty = Decimal(str(row.get("quantity_kg") or 0))
    return {
        "work_order_code": str(row.get("work_order_code") or ""),
        "grade": row.get("grade"),
        "ctc": row.get("ctc"),
        "quantity_kg": str(qty),
        "loaded_kg": str(loaded),
        "fulfilled_kg": str(fulfilled),
        "status": row.get("status") or "OPEN",
        "created_at": row.get("created_at"),
        "created_by": row.get("created_by"),
        "kiln_resource_code": row.get("kiln_resource_code"),
    }


def list_work_orders(db: Session, tenant: TenantContext) -> list[dict[str, Any]]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(META_KEY)
    if not isinstance(block, list):
        return []
    return [_row_out(item) for item in block if isinstance(item, dict) and item.get("work_order_code")]


def get_work_order(db: Session, tenant: TenantContext, code: str) -> dict[str, Any]:
    wanted = (code or "").strip()
    for row in list_work_orders(db, tenant):
        if row["work_order_code"] == wanted:
            return row
    raise ValidationError(f"Work order '{wanted}' was not found.")


def lookup_work_order_ctc(
    db: Session, tenant: TenantContext, code: str | None, cache: dict | None = None
) -> str | None:
    wanted = (code or "").strip()
    if not wanted:
        return None
    if cache is not None and wanted in cache:
        return cache[wanted]
    try:
        value = str(get_work_order(db, tenant, wanted).get("ctc") or "").strip() or None
    except ValidationError:
        value = None
    if cache is not None:
        cache[wanted] = value
    return value


def delete_work_order(db: Session, tenant: TenantContext, code: str) -> dict[str, Any]:
    wanted = (code or "").strip()
    tenant_row = _tenant_row(db, tenant)
    meta = dict(tenant_row.metadata_ if isinstance(tenant_row.metadata_, dict) else {})
    rows = list(meta.get(META_KEY) or [])
    found = None
    kept = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("work_order_code") or "") == wanted:
            found = item
            continue
        kept.append(item)
    if found is None:
        raise ValidationError(f"Work order '{wanted}' was not found.")
    loaded = Decimal(str(found.get("loaded_kg") or 0))
    fulfilled = Decimal(str(found.get("fulfilled_kg") or 0))
    if loaded > 0 or fulfilled > 0:
        raise ValidationError(
            f"Work order '{wanted}' already has kiln feed or fulfilled quantity and cannot be deleted."
        )
    meta[META_KEY] = kept
    tenant_row.metadata_ = meta
    flag_modified(tenant_row, "metadata_")
    db.commit()
    return _row_out(found)


def create_work_order(
    db: Session,
    tenant: TenantContext,
    *,
    grade: str,
    ctc: Any,
    quantity_kg: Any,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    label = ac_inbound_admin._canonical_outward_grade(grade)
    if not ac_inbound_workflow._is_kiln_feed_grade(label):
        raise ValidationError("Work order grade must be a kiln-feed grade (not Unburnt or Stones).")
    allowed = {ac_inbound_admin._canonical_outward_grade(item) for item in kiln_feed_grade_options(db, tenant)}
    if allowed and ac_inbound_admin._canonical_outward_grade(label) not in allowed:
        raise ValidationError(f"Unknown kiln-feed grade '{grade}'.")
    rounded = ac_process_rules.round_ctc(ctc)
    if rounded is None:
        raise ValidationError("Work order CTC is required.")
    qty = _as_kg(quantity_kg)
    code = generate_ac_business_code(db, "ac_work_order", tenant_id=tenant.tenant_id)
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "work_order_code": code,
        "grade": label,
        "ctc": str(rounded),
        "quantity_kg": str(qty),
        "loaded_kg": "0",
        "fulfilled_kg": "0",
        "status": "OPEN",
        "created_at": now,
        "created_by": (user_id or "").strip() or None,
        "kiln_resource_code": None,
        "loads": [],
    }
    tenant_row = _tenant_row(db, tenant)
    meta = dict(tenant_row.metadata_ if isinstance(tenant_row.metadata_, dict) else {})
    rows = list(meta.get(META_KEY) or [])
    if not isinstance(rows, list):
        rows = []
    rows.append(entry)
    meta[META_KEY] = rows
    tenant_row.metadata_ = meta
    flag_modified(tenant_row, "metadata_")
    db.commit()
    db.refresh(tenant_row)
    return _row_out(entry)


def record_work_order_load(
    db: Session,
    tenant: TenantContext,
    *,
    work_order_code: str,
    quantity_kg: Any,
    kiln_resource_code: Optional[str] = None,
    bag_code: Optional[str] = None,
    lot_code: Optional[str] = None,
    commit: bool = False,
) -> dict[str, Any]:
    wanted = (work_order_code or "").strip()
    feed_kg = _as_kg(quantity_kg)
    tenant_row = _tenant_row(db, tenant)
    meta = dict(tenant_row.metadata_ if isinstance(tenant_row.metadata_, dict) else {})
    rows = list(meta.get(META_KEY) or [])
    found = None
    for item in rows:
        if isinstance(item, dict) and str(item.get("work_order_code") or "") == wanted:
            found = item
            break
    if found is None:
        raise ValidationError(f"Work order '{wanted}' was not found.")
    qty = Decimal(str(found.get("quantity_kg") or 0))
    loaded = Decimal(str(found.get("loaded_kg") or 0)) + feed_kg
    loads = list(found.get("loads") or [])
    loads.append(
        {
            "kg": str(feed_kg),
            "bag_code": bag_code,
            "lot_code": lot_code,
            "kiln_resource_code": kiln_resource_code,
            "loaded_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    found["loaded_kg"] = str(loaded)
    found["loads"] = loads
    if kiln_resource_code:
        found["kiln_resource_code"] = kiln_resource_code
    if loaded >= qty - Decimal("0.001"):
        found["status"] = "LOADED"
    else:
        found["status"] = "IN_PROGRESS"
    meta[META_KEY] = rows
    tenant_row.metadata_ = meta
    flag_modified(tenant_row, "metadata_")
    if commit:
        db.commit()
        db.refresh(tenant_row)
    return _row_out(found)


def record_work_order_output(
    db: Session,
    tenant: TenantContext,
    *,
    work_order_code: str,
    quantity_kg: Any,
    bag_code: Optional[str] = None,
    kiln_resource_code: Optional[str] = None,
    ctc_match: bool = False,
    commit: bool = False,
) -> dict[str, Any]:
    wanted = (work_order_code or "").strip()
    out_kg = _as_kg(quantity_kg)
    tenant_row = _tenant_row(db, tenant)
    meta = dict(tenant_row.metadata_ if isinstance(tenant_row.metadata_, dict) else {})
    rows = list(meta.get(META_KEY) or [])
    found = None
    for item in rows:
        if isinstance(item, dict) and str(item.get("work_order_code") or "") == wanted:
            found = item
            break
    if found is None:
        raise ValidationError(f"Work order '{wanted}' was not found.")
    outputs = list(found.get("outputs") or [])
    outputs.append(
        {
            "kg": str(out_kg),
            "bag_code": bag_code,
            "kiln_resource_code": kiln_resource_code,
            "ctc_match": bool(ctc_match),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    found["outputs"] = outputs
    if ctc_match:
        fulfilled = Decimal(str(found.get("fulfilled_kg") or 0)) + out_kg
        found["fulfilled_kg"] = str(fulfilled)
        qty = Decimal(str(found.get("quantity_kg") or 0))
        if fulfilled >= qty - Decimal("0.001"):
            found["status"] = "FULFILLED"
    meta[META_KEY] = rows
    tenant_row.metadata_ = meta
    flag_modified(tenant_row, "metadata_")
    if commit:
        db.commit()
        db.refresh(tenant_row)
    return _row_out(found)
