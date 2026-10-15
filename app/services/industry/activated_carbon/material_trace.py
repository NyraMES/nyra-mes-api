"""Plant-facing material trace: bag / work order / inward / dispatch → supplier.

Walks existing inward bags, kiln-feed events, output parent links, and dispatch
bag lists. Supplier is read only from the inward (document ``supplies`` chain).
Customer is not included. Kiln blend can list more than one supplier.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import CustomerOrder, ProductionLot, QualityCheck, Resource, Supplier
from app.schemas.mes_core.schemas import (
    AcMaterialTraceOptionOut,
    AcMaterialTraceOptionsOut,
    AcMaterialTraceOut,
    AcTraceStepOut,
    AcTraceSupplierShareOut,
)
from app.services.industry.activated_carbon import process_rules as ac_process_rules
from app.services.industry.activated_carbon import work_orders as ac_work_orders
from app.services.industry.activated_carbon.post_activation import _is_in_stock_destination
from app.services.mes_core.base import TenantRepository

STAGE_LABELS = {
    "gate": "Gate receipt",
    "rms_bag": "RMS bag",
    "ro_bag": "RO bag",
    "kiln_feed": "Kiln feed",
    "kiln_output": "Kiln output",
    "destoning": "Destoning",
    "screening": "Screening",
    "dedusting": "De-dusting",
    "crushing": "Crushing",
    "demagnetisation": "De-magnetisation",
    "blending": "Blending",
    "fg_qc": "In Stock",
    "in_stock": "In Stock",
    "dispatch": "Dispatch",
}

STAGE_ORDER = {key: idx for idx, key in enumerate(STAGE_LABELS)}

_POST_STAGES = {
    "screening",
    "dedusting",
    "crushing",
    "demagnetisation",
    "blending",
    "fg_qc",
}


@dataclass
class InwardRef:
    order_code: str
    supplier_code: str = ""
    supplier_name: str = ""
    dc_number: str = ""
    kg: Decimal = Decimal("0")
    at: str | None = None
    rms_bags: list[str] = field(default_factory=list)
    ro_bags: list[str] = field(default_factory=list)


@dataclass
class BagRef:
    bag_code: str
    stage: str
    kg: Decimal = Decimal("0")
    inward_code: str | None = None
    work_order_code: str | None = None
    input_bag_codes: list[str] = field(default_factory=list)
    machine: str | None = None
    mesh: str | None = None
    grade: str | None = None
    ctc: str | None = None
    stones: str | None = None
    destination: str | None = None
    at: str | None = None
    prior_work_order_codes: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class FeedEvent:
    bag_code: str
    kg: Decimal
    work_order_code: str
    kiln_code: str | None = None
    inward_code: str | None = None
    at: str | None = None


@dataclass
class DispatchRef:
    dispatch_code: str
    work_order_code: str | None = None
    bag_codes: list[str] = field(default_factory=list)
    kg: Decimal = Decimal("0")
    at: str | None = None


@dataclass
class TraceIndex:
    inwards: dict[str, InwardRef] = field(default_factory=dict)
    bags: dict[str, list[BagRef]] = field(default_factory=dict)
    feeds: list[FeedEvent] = field(default_factory=list)
    dispatches: dict[str, DispatchRef] = field(default_factory=dict)
    bag_to_inward: dict[str, str] = field(default_factory=dict)
    work_orders: set[str] = field(default_factory=set)
    work_order_at: dict[str, str] = field(default_factory=dict)


def classify_query(raw: str) -> str:
    text = (raw or "").strip().upper()
    if text.startswith("WO-"):
        return "work_order"
    if text.startswith("ORD-"):
        return "inward"
    if text.startswith("DISP-"):
        return "dispatch"
    return "bag"


def _dec(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _add_bag(index: TraceIndex, ref: BagRef) -> None:
    if not ref.bag_code:
        return
    index.bags.setdefault(ref.bag_code, []).append(ref)
    if ref.inward_code:
        index.bag_to_inward.setdefault(ref.bag_code, ref.inward_code)
    if ref.work_order_code:
        index.work_orders.add(ref.work_order_code)
    for code in ref.prior_work_order_codes or []:
        if code:
            index.work_orders.add(code)


def _inward_of(index: TraceIndex, bag_code: str | None, hinted: str | None = None) -> str | None:
    if hinted and hinted in index.inwards:
        return hinted
    code = (bag_code or "").strip()
    if not code:
        return None
    return index.bag_to_inward.get(code)


def _history_work_orders(bag: dict) -> list[str]:
    codes: list[str] = []
    for row in bag.get("work_order_history") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("from_work_order_code") or "").strip()
        if code:
            codes.append(code)
    return codes


def _bag_used_work_order(ref: BagRef, code: str) -> bool:
    return ref.work_order_code == code or code in (ref.prior_work_order_codes or [])


def _work_order_codes_for(index: TraceIndex, bag_codes: Iterable[str]) -> list[str]:
    codes: list[str] = []
    for bag_code in bag_codes:
        for ref in index.bags.get(bag_code) or []:
            if ref.work_order_code:
                codes.append(ref.work_order_code)
            codes.extend(ref.prior_work_order_codes or [])
    for feed in index.feeds:
        if feed.bag_code in set(bag_codes) and feed.work_order_code:
            codes.append(feed.work_order_code)
    return _unique(codes)


def _unique(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _parent_codes(index: TraceIndex, bag_code: str) -> list[str]:
    codes: list[str] = []
    work_order = None
    for ref in index.bags.get(bag_code) or []:
        codes.extend(ref.input_bag_codes)
        work_order = work_order or ref.work_order_code
    codes = _unique(codes)
    if codes:
        return codes
    if work_order:
        return _unique(
            feed.bag_code
            for feed in index.feeds
            if feed.work_order_code == work_order and feed.bag_code
        )
    return []


def _ancestor_bags(index: TraceIndex, start: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if not current or current in seen:
            continue
        seen.add(current)
        if current != start:
            found.append(current)
        for parent in _parent_codes(index, current):
            if parent not in seen:
                stack.append(parent)
    return found


def _child_bags(index: TraceIndex, start: str) -> list[str]:
    found: list[str] = []
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for bag_code, refs in index.bags.items():
            if bag_code in seen:
                continue
            if any(current in ref.input_bag_codes for ref in refs):
                seen.add(bag_code)
                found.append(bag_code)
                stack.append(bag_code)
    return found


def _supplier_shares(
    index: TraceIndex,
    inward_codes: list[str],
    feed_kg_by_inward: dict[str, Decimal],
) -> list[AcTraceSupplierShareOut]:
    grouped: dict[tuple[str, str], dict] = {}
    for code in inward_codes:
        inward = index.inwards.get(code)
        if inward is None:
            continue
        key = (inward.supplier_code or "—", inward.supplier_name or "Unknown supplier")
        row = grouped.setdefault(
            key,
            {"codes": [], "kg": Decimal("0")},
        )
        row["codes"].append(code)
        feed = feed_kg_by_inward.get(code)
        row["kg"] += feed if feed is not None else inward.kg
    shares = [
        AcTraceSupplierShareOut(
            supplier_code=code or None,
            supplier_name=name,
            inward_codes=row["codes"],
            feed_kg=row["kg"],
        )
        for (code, name), row in grouped.items()
    ]
    shares.sort(key=lambda row: (-row.feed_kg, row.supplier_name or ""))
    return shares


def _kiln_parameter_note(raw) -> str | None:
    if not isinstance(raw, dict) or not raw:
        return None
    labels = {
        "residence_time_min": "Residence min",
        "zone1_temp_c": "Zone 1 °C",
        "zone2_temp_c": "Zone 2 °C",
        "steam_flow_kg_h": "Steam kg/h",
        "o2_pct": "Oxygen %",
        "kiln_temp_c": "Kiln temp °C",
        "pressure_bar": "Pressure bar",
    }
    parts = []
    for key, value in raw.items():
        if value in (None, "") or "scrap" in str(key).lower():
            continue
        parts.append(f"{labels.get(str(key), str(key))} {value}")
    if not parts:
        return None
    return "Kiln settings: " + " · ".join(parts)


def _step(
    *,
    stage: str,
    bag_code: str | None = None,
    inward_code: str | None = None,
    work_order_code: str | None = None,
    dispatch_code: str | None = None,
    kg: Decimal | None = None,
    machine: str | None = None,
    mesh: str | None = None,
    grade: str | None = None,
    ctc: str | None = None,
    stones: str | None = None,
    destination: str | None = None,
    at: str | None = None,
    note: str | None = None,
) -> AcTraceStepOut:
    return AcTraceStepOut(
        stage=stage,
        stage_label=STAGE_LABELS.get(stage, stage),
        bag_code=bag_code,
        inward_code=inward_code,
        work_order_code=work_order_code,
        dispatch_code=dispatch_code,
        kg=kg,
        machine=machine,
        mesh=mesh,
        grade=grade,
        ctc=ctc,
        stones=stones,
        destination=destination,
        at=at,
        note=note,
    )


def _bag_steps(index: TraceIndex, bag_codes: Iterable[str]) -> list[AcTraceStepOut]:
    steps: list[AcTraceStepOut] = []
    seen: set[tuple[str, str]] = set()
    for bag_code in _unique(bag_codes):
        for ref in index.bags.get(bag_code) or []:
            key = (ref.stage, ref.bag_code)
            if key in seen:
                continue
            seen.add(key)
            steps.append(
                _step(
                    stage=ref.stage,
                    bag_code=ref.bag_code,
                    inward_code=ref.inward_code or _inward_of(index, ref.bag_code),
                    work_order_code=ref.work_order_code,
                    kg=ref.kg,
                    machine=ref.machine,
                    mesh=ref.mesh,
                    grade=ref.grade,
                    ctc=ref.ctc,
                    stones=ref.stones,
                    destination=ref.destination,
                    at=ref.at,
                    note=ref.note,
                )
            )
            if _is_in_stock_destination(ref.destination or ""):
                stock_key = ("in_stock", ref.bag_code)
                if stock_key not in seen:
                    seen.add(stock_key)
                    steps.append(
                        _step(
                            stage="in_stock",
                            bag_code=ref.bag_code,
                            inward_code=ref.inward_code or _inward_of(index, ref.bag_code),
                            work_order_code=ref.work_order_code,
                            kg=ref.kg,
                            grade=ref.grade,
                            at=ref.at,
                        )
                    )
    return steps


def _inward_steps(index: TraceIndex, order_code: str) -> list[AcTraceStepOut]:
    inward = index.inwards.get(order_code)
    if inward is None:
        return []
    steps = [
        _step(
            stage="gate",
            inward_code=inward.order_code,
            kg=inward.kg,
            at=inward.at,
            note=f"DC {inward.dc_number}" if inward.dc_number else None,
        )
    ]
    steps.extend(_bag_steps(index, inward.rms_bags + inward.ro_bags))
    return steps


def _feed_steps(index: TraceIndex, work_order: str | None, bag_codes: Iterable[str] | None = None) -> list[AcTraceStepOut]:
    wanted_bags = set(_unique(bag_codes or []))
    steps: list[AcTraceStepOut] = []
    for feed in index.feeds:
        if work_order and feed.work_order_code != work_order:
            continue
        if wanted_bags and feed.bag_code not in wanted_bags:
            continue
        steps.append(
            _step(
                stage="kiln_feed",
                bag_code=feed.bag_code,
                inward_code=feed.inward_code or _inward_of(index, feed.bag_code),
                work_order_code=feed.work_order_code,
                kg=feed.kg,
                machine=feed.kiln_code,
                at=feed.at,
            )
        )
    return steps


def _dispatch_steps(index: TraceIndex, codes: Iterable[str]) -> list[AcTraceStepOut]:
    steps: list[AcTraceStepOut] = []
    for code in _unique(codes):
        row = index.dispatches.get(code)
        if row is None:
            continue
        steps.append(
            _step(
                stage="dispatch",
                dispatch_code=row.dispatch_code,
                work_order_code=row.work_order_code,
                kg=row.kg,
                at=row.at,
                note=", ".join(row.bag_codes) if row.bag_codes else None,
            )
        )
    return steps


def _sort_steps(steps: list[AcTraceStepOut]) -> list[AcTraceStepOut]:
    return sorted(
        steps,
        key=lambda row: (STAGE_ORDER.get(row.stage, 99), str(row.at or ""), row.bag_code or ""),
    )


def _feeds_for(index: TraceIndex, work_order: str | None, bag_codes: Iterable[str]) -> list[FeedEvent]:
    bags = set(_unique(bag_codes))
    out: list[FeedEvent] = []
    for feed in index.feeds:
        if work_order and feed.work_order_code == work_order:
            out.append(feed)
        elif feed.bag_code in bags:
            out.append(feed)
    return out


def _inwards_and_feed_kg(
    index: TraceIndex,
    *,
    work_order: str | None = None,
    bag_codes: Iterable[str] = (),
    inward_codes: Iterable[str] = (),
) -> tuple[list[str], dict[str, Decimal]]:
    feed_kg: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    codes = _unique(inward_codes)
    for feed in _feeds_for(index, work_order, bag_codes):
        inward = feed.inward_code or _inward_of(index, feed.bag_code)
        if not inward:
            continue
        if inward not in codes:
            codes.append(inward)
        feed_kg[inward] += feed.kg
    for bag_code in _unique(bag_codes):
        inward = _inward_of(index, bag_code)
        if inward and inward not in codes:
            codes.append(inward)
    return codes, dict(feed_kg)


def resolve_trace(index: TraceIndex, query: str) -> AcMaterialTraceOut:
    raw = (query or "").strip()
    if not raw:
        raise ValidationError("Enter a work order, bag, inward, or dispatch code.")
    kind = classify_query(raw)
    key = raw.upper() if kind != "bag" else raw
    # Bag codes are stored as entered; compare case-insensitively.
    bag_key = next((code for code in index.bags if code.upper() == raw.upper()), raw)
    wo_key = next((code for code in index.work_orders if code.upper() == raw.upper()), key)
    inward_key = next((code for code in index.inwards if code.upper() == raw.upper()), key)
    dispatch_key = next((code for code in index.dispatches if code.upper() == raw.upper()), key)

    work_order = None
    bag_code = None
    inward_codes: list[str] = []
    dispatch_codes: list[str] = []
    bag_codes: list[str] = []
    steps: list[AcTraceStepOut] = []
    message = None

    if kind == "inward":
        if inward_key not in index.inwards:
            return _empty(raw, kind, "No inward with that number.")
        inward_codes = [inward_key]
        inward = index.inwards[inward_key]
        bag_codes = inward.rms_bags + inward.ro_bags
        children: list[str] = []
        for code in list(bag_codes):
            children.extend(_child_bags(index, code))
        bag_codes = _unique(bag_codes + children)
        wo_from_feeds = _unique(
            feed.work_order_code
            for feed in index.feeds
            if (feed.inward_code or _inward_of(index, feed.bag_code)) == inward_key
        )
        work_order = wo_from_feeds[0] if len(wo_from_feeds) == 1 else None
        steps = (
            _inward_steps(index, inward_key)
            + _feed_steps(index, None, bag_codes)
            + _bag_steps(index, children)
            + _dispatch_steps(
                index,
                (
                    code
                    for code, row in index.dispatches.items()
                    if row.work_order_code in wo_from_feeds
                    or any(bag in bag_codes + children for bag in row.bag_codes)
                ),
            )
        )
        dispatch_codes = _unique(
            step.dispatch_code for step in steps if step.dispatch_code
        )
    elif kind == "work_order":
        if wo_key not in index.work_orders:
            return _empty(raw, kind, "No work order with that number.")
        work_order = wo_key
        feed_bags = [feed.bag_code for feed in index.feeds if feed.work_order_code == wo_key]
        wo_bags = [
            code
            for code, refs in index.bags.items()
            if any(_bag_used_work_order(ref, wo_key) for ref in refs)
        ]
        bag_codes = _unique(feed_bags + wo_bags)
        inward_codes, _ = _inwards_and_feed_kg(index, work_order=wo_key, bag_codes=bag_codes)
        for code in inward_codes:
            steps.extend(_inward_steps(index, code))
        steps.extend(_feed_steps(index, wo_key))
        steps.extend(_bag_steps(index, wo_bags))
        dispatch_codes = [
            code for code, row in index.dispatches.items() if row.work_order_code == wo_key
        ]
        steps.extend(_dispatch_steps(index, dispatch_codes))
        if not any(feed.work_order_code == wo_key for feed in index.feeds):
            message = "No kiln feed yet — supplier appears after RO bags are loaded."
    elif kind == "dispatch":
        row = index.dispatches.get(dispatch_key)
        if row is None:
            return _empty(raw, kind, "No dispatch with that number.")
        dispatch_codes = [dispatch_key]
        work_order = row.work_order_code
        bag_codes = list(row.bag_codes)
        if work_order:
            wo_bags = [
                code
                for code, refs in index.bags.items()
                if any(_bag_used_work_order(ref, work_order) for ref in refs)
            ]
            bag_codes = _unique(bag_codes + wo_bags)
        ancestors: list[str] = []
        for code in bag_codes:
            ancestors.extend(_ancestor_bags(index, code))
        inward_codes, _ = _inwards_and_feed_kg(
            index, work_order=work_order, bag_codes=bag_codes + ancestors
        )
        for code in inward_codes:
            steps.extend(_inward_steps(index, code))
        steps.extend(_feed_steps(index, work_order, bag_codes + ancestors))
        steps.extend(_bag_steps(index, bag_codes + ancestors))
        steps.extend(_dispatch_steps(index, dispatch_codes))
    else:
        if bag_key not in index.bags:
            return _empty(raw, kind, "No bag with that code.")
        bag_code = bag_key
        ancestors = _ancestor_bags(index, bag_key)
        children = _child_bags(index, bag_key)
        bag_codes = _unique([bag_key, *ancestors, *children])
        refs = index.bags.get(bag_key) or []
        work_order = next((ref.work_order_code for ref in refs if ref.work_order_code), None)
        if work_order is None:
            work_order = next(
                (feed.work_order_code for feed in index.feeds if feed.bag_code == bag_key),
                None,
            )
        inward_codes, _ = _inwards_and_feed_kg(
            index, work_order=work_order, bag_codes=bag_codes
        )
        hinted = _inward_of(index, bag_key)
        if hinted and hinted not in inward_codes:
            inward_codes.insert(0, hinted)
        for code in inward_codes:
            steps.extend(_inward_steps(index, code))
        steps.extend(_feed_steps(index, work_order, bag_codes))
        steps.extend(_bag_steps(index, bag_codes))
        dispatch_codes = [
            code
            for code, row in index.dispatches.items()
            if bag_key in row.bag_codes or (work_order and row.work_order_code == work_order)
        ]
        steps.extend(_dispatch_steps(index, dispatch_codes))

    if kind == "inward":
        inward_codes = [inward_key]
        feed_kg = {
            inward_key: sum(
                (feed.kg for feed in index.feeds if (feed.inward_code or _inward_of(index, feed.bag_code)) == inward_key),
                Decimal("0"),
            )
        }
    else:
        inward_codes, feed_kg = _inwards_and_feed_kg(
            index,
            work_order=work_order,
            bag_codes=bag_codes,
            inward_codes=inward_codes,
        )
    suppliers = _supplier_shares(index, inward_codes, feed_kg)
    blend = kind != "inward" and len(suppliers) > 1
    return AcMaterialTraceOut(
        found=True,
        query=raw,
        query_kind=kind,
        work_order_code=work_order,
        work_order_codes=_work_order_codes_for(index, bag_codes),
        bag_code=bag_code,
        inward_codes=inward_codes,
        dispatch_codes=dispatch_codes,
        suppliers=suppliers,
        blend=blend,
        steps=_sort_steps(steps),
        message=message
        or (
            "More than one supplier fed this work order (kiln blend)."
            if blend
            else None
        ),
    )


def _empty(query: str, kind: str, message: str) -> AcMaterialTraceOut:
    return AcMaterialTraceOut(
        found=False,
        query=query,
        query_kind=kind,
        message=message,
    )


def _meta(row) -> dict:
    data = getattr(row, "metadata_", None)
    return data if isinstance(data, dict) else {}


def _stones_label(values: dict | None) -> str | None:
    raw = ac_process_rules.destoning_stones_from_values(values)
    if raw in (None, ""):
        return None
    try:
        present = ac_process_rules.destoning_stones_present(raw)
    except ValidationError:
        return str(raw)
    if present is True:
        return "Yes"
    if present is False:
        return "No"
    return str(raw)


def _qc_values(bag: dict, key: str) -> dict:
    block = bag.get(key)
    if not isinstance(block, dict):
        return {}
    values = block.get("values")
    return values if isinstance(values, dict) else {}


def build_trace_index(db: Session, tenant: TenantContext) -> TraceIndex:
    repo = TenantRepository(db, tenant)
    index = TraceIndex()
    suppliers = {
        row.supplier_id: row
        for row in repo.query(Supplier).all()
        if getattr(row, "supplier_id", None)
    }
    lot_inward: dict[str, str] = {}
    for lot in repo.query(ProductionLot).all():
        meta = _meta(lot)
        inward_code = str(meta.get("source_inward_order_code") or "").strip()
        if lot.lot_code and inward_code:
            lot_inward[str(lot.lot_code)] = inward_code
        for bag in meta.get("crusher_outward_bags") or []:
            if not isinstance(bag, dict) or not bag.get("bag_code"):
                continue
            code = str(bag.get("bag_code"))
            if inward_code:
                index.bag_to_inward.setdefault(code, inward_code)

    for order in repo.query(CustomerOrder).all():
        meta = _meta(order)
        if meta.get("flow") == "CUSTOMER_SALES":
            continue
        receipt = meta.get("inward_receipt") if isinstance(meta.get("inward_receipt"), dict) else {}
        supplier = suppliers.get(order.supplier_id) if order.supplier_id else None
        our_kg = receipt.get("our_weight_kg")
        inward = InwardRef(
            order_code=str(order.order_code or ""),
            supplier_code=str(getattr(supplier, "supplier_code", "") or ""),
            supplier_name=str(getattr(supplier, "supplier_name", "") or ""),
            dc_number=str(receipt.get("dc_number") or ""),
            kg=_dec(our_kg if our_kg is not None else receipt.get("supplier_weight_kg")),
            at=order.created_at.isoformat() if order.created_at else None,
        )
        if not inward.order_code:
            continue
        for bag in meta.get("inward_bags") or []:
            if not isinstance(bag, dict) or not bag.get("bag_code"):
                continue
            code = str(bag.get("bag_code"))
            grade = str(bag.get("grade") or bag.get("grade_label") or "").strip() or None
            stage = "ro_bag" if grade else "rms_bag"
            kg = _dec(bag.get("weight_kg") or bag.get("quantity_kg"))
            _add_bag(
                index,
                BagRef(
                    bag_code=code,
                    stage=stage,
                    kg=kg,
                    inward_code=inward.order_code,
                    grade=grade,
                    at=str(bag.get("created_at") or inward.at or "") or None,
                ),
            )
            if stage == "rms_bag":
                inward.rms_bags.append(code)
            else:
                inward.ro_bags.append(code)
        for bag in meta.get("crusher_outward_bags") or []:
            if not isinstance(bag, dict) or not bag.get("bag_code"):
                continue
            code = str(bag.get("bag_code"))
            if code not in inward.ro_bags:
                inward.ro_bags.append(code)
            if code not in index.bags:
                _add_bag(
                    index,
                    BagRef(
                        bag_code=code,
                        stage="ro_bag",
                        kg=_dec(bag.get("weight_kg") or bag.get("quantity_kg")),
                        inward_code=inward.order_code,
                        grade=str(bag.get("grade") or "").strip() or None,
                    ),
                )
        if inward.order_code and (
            inward.supplier_code
            or inward.rms_bags
            or inward.ro_bags
            or meta.get("flow") == "RAW_MATERIAL_INWARD"
        ):
            index.inwards[inward.order_code] = inward

    for resource in repo.query(Resource).all():
        meta = _meta(resource)
        kiln_code = str(resource.resource_code or "") or None
        for event in meta.get("kiln_feed_events") or []:
            if not isinstance(event, dict):
                continue
            bag_code = str(event.get("bag_code") or "").strip()
            wo = str(event.get("work_order_code") or "").strip()
            if not bag_code and not wo:
                continue
            inward = _inward_of(index, bag_code) or lot_inward.get(str(event.get("lot_code") or ""))
            feed = FeedEvent(
                bag_code=bag_code,
                kg=_dec(event.get("kg") or event.get("quantity_kg")),
                work_order_code=wo,
                kiln_code=str(event.get("kiln_resource_code") or kiln_code or "") or None,
                inward_code=inward,
                at=str(event.get("loaded_at") or "") or None,
            )
            if wo:
                index.work_orders.add(wo)
            if bag_code and inward:
                index.bag_to_inward.setdefault(bag_code, inward)
            index.feeds.append(feed)
        for bag in meta.get("kiln_output_bags") or []:
            if not isinstance(bag, dict) or not bag.get("bag_code"):
                continue
            qc = _qc_values(bag, "kiln_output_qc") or _qc_values(bag, "output_qc")
            wo = str(bag.get("work_order_code") or "").strip() or None
            _add_bag(
                index,
                BagRef(
                    bag_code=str(bag.get("bag_code")),
                    stage="kiln_output",
                    kg=_dec(bag.get("quantity_kg")),
                    work_order_code=wo,
                    prior_work_order_codes=_history_work_orders(bag),
                    input_bag_codes=[str(c) for c in (bag.get("input_bag_codes") or []) if c],
                    machine=str(bag.get("kiln_resource_code") or kiln_code or "") or None,
                    ctc=str(qc.get("ctc") or bag.get("ctc") or "").strip() or None,
                    at=str(bag.get("created_at") or "") or None,
                    note=_kiln_parameter_note(bag.get("kiln_parameters")),
                ),
            )
        for bag in meta.get("destoning_output_bags") or []:
            if not isinstance(bag, dict) or not bag.get("bag_code"):
                continue
            qc = _qc_values(bag, "destoning_qc")
            dest = (
                qc.get("deston_qc_destination")
                or bag.get("destination")
                or ""
            )
            _add_bag(
                index,
                BagRef(
                    bag_code=str(bag.get("bag_code")),
                    stage="destoning",
                    kg=_dec(bag.get("quantity_kg")),
                    work_order_code=str(bag.get("work_order_code") or "").strip() or None,
                    prior_work_order_codes=_history_work_orders(bag),
                    input_bag_codes=[str(c) for c in (bag.get("input_bag_codes") or []) if c],
                    machine=str(
                        bag.get("destoner_resource_code") or resource.resource_code or ""
                    )
                    or None,
                    ctc=str(bag.get("ctc") or "").strip() or None,
                    stones=_stones_label(qc),
                    destination=str(dest).strip() or None,
                    at=str(bag.get("created_at") or "") or None,
                ),
            )
        stations = meta.get("stations")
        if isinstance(stations, dict):
            for process, state in stations.items():
                stage = str(process or "").strip().lower()
                if stage not in _POST_STAGES:
                    continue
                block = state if isinstance(state, dict) else {}
                for bag in (block.get("output_bags") or []) + (block.get("loaded_bags") or []):
                    if not isinstance(bag, dict) or not bag.get("bag_code"):
                        continue
                    qc = _qc_values(bag, "quality_qc")
                    dest = qc.get("post_qc_destination") or bag.get("destination") or ""
                    listed_stage = "in_stock" if _is_in_stock_destination(str(dest)) else stage
                    _add_bag(
                        index,
                        BagRef(
                            bag_code=str(bag.get("bag_code")),
                            stage=listed_stage if listed_stage in STAGE_LABELS else stage,
                            kg=_dec(bag.get("quantity_kg") or bag.get("remaining_kg")),
                            work_order_code=str(bag.get("work_order_code") or "").strip() or None,
                            prior_work_order_codes=_history_work_orders(bag),
                            input_bag_codes=[
                                str(c) for c in (bag.get("input_bag_codes") or []) if c
                            ],
                            machine=str(resource.resource_name or resource.resource_code or "")
                            or None,
                            mesh=str(bag.get("mesh") or "").strip() or None,
                            grade=str(bag.get("grade") or "").strip() or None,
                            destination=str(dest).strip() or None,
                            at=str(bag.get("created_at") or bag.get("loaded_at") or "") or None,
                        ),
                    )

    for row in (
        repo.query(QualityCheck)
        .filter(QualityCheck.check_type == "DISPATCH")
        .all()
    ):
        meta = _meta(row)
        bags: list[str] = []
        kg = Decimal("0")
        for line in meta.get("lines") or []:
            if not isinstance(line, dict):
                continue
            kg += _dec(line.get("dispatch_quantity"))
            bags.extend(str(code) for code in (line.get("bag_codes") or []) if code)
        if kg <= 0:
            kg = _dec(meta.get("last_dispatch_kg"))
        code = str(row.check_code or "").strip()
        if not code:
            continue
        index.dispatches[code] = DispatchRef(
            dispatch_code=code,
            work_order_code=str(meta.get("work_order_code") or "").strip() or None,
            bag_codes=_unique(bags),
            kg=kg,
            at=str(meta.get("dispatch_date") or (row.created_at.isoformat() if row.created_at else ""))
            or None,
        )
        if index.dispatches[code].work_order_code:
            index.work_orders.add(index.dispatches[code].work_order_code)

    for row in ac_work_orders.list_work_orders(db, tenant):
        code = str(row.get("work_order_code") or "").strip()
        if not code:
            continue
        index.work_orders.add(code)
        created = row.get("created_at")
        if created:
            index.work_order_at[code] = (
                created.isoformat() if hasattr(created, "isoformat") else str(created)
            )
    return index


def _parse_at(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None


def _in_month(value: object, year: int, month: int) -> bool:
    parsed = _parse_at(value)
    return parsed is not None and parsed.year == year and parsed.month == month


def _month_parts(month: str | None = None) -> tuple[int, int, str, str]:
    if month:
        try:
            year_s, month_s = month.split("-", 1)
            year, month_n = int(year_s), int(month_s)
        except (TypeError, ValueError):
            raise ValidationError("Month must be YYYY-MM.")
        if month_n < 1 or month_n > 12:
            raise ValidationError("Month must be YYYY-MM.")
    else:
        now = datetime.now()
        year, month_n = now.year, now.month
    key = f"{year:04d}-{month_n:02d}"
    label = datetime(year, month_n, 1).strftime("%b %Y")
    return year, month_n, key, label


def _work_order_in_month(index: TraceIndex, code: str, year: int, month: int) -> bool:
    if _in_month(index.work_order_at.get(code), year, month):
        return True
    if any(_in_month(feed.at, year, month) and feed.work_order_code == code for feed in index.feeds):
        return True
    if any(
        _in_month(ref.at, year, month) and ref.work_order_code == code
        for refs in index.bags.values()
        for ref in refs
    ):
        return True
    return any(
        _in_month(row.at, year, month) and row.work_order_code == code
        for row in index.dispatches.values()
    )


def _bag_in_month(index: TraceIndex, bag_code: str, year: int, month: int) -> bool:
    refs = index.bags.get(bag_code) or []
    if any(_in_month(ref.at, year, month) for ref in refs):
        return True
    inward = _inward_of(index, bag_code)
    if inward and inward in index.inwards and _in_month(index.inwards[inward].at, year, month):
        return True
    if any(_in_month(feed.at, year, month) and feed.bag_code == bag_code for feed in index.feeds):
        return True
    wo = next((ref.work_order_code for ref in refs if ref.work_order_code), None)
    return bool(wo and _work_order_in_month(index, wo, year, month))


def list_trace_options(
    index: TraceIndex,
    kind: str,
    month: str | None = None,
) -> AcMaterialTraceOptionsOut:
    wanted = (kind or "work_order").strip().lower()
    if wanted not in {"work_order", "bag", "inward", "dispatch"}:
        raise ValidationError("Choose work order, bag, inward, or dispatch.")
    year, month_n, month_key, month_label = _month_parts(month)
    options: list[AcMaterialTraceOptionOut] = []
    if wanted == "work_order":
        for code in sorted(index.work_orders):
            if not _work_order_in_month(index, code, year, month_n):
                continue
            at = index.work_order_at.get(code)
            options.append(AcMaterialTraceOptionOut(code=code, kind=wanted, label=code, at=at))
    elif wanted == "inward":
        for inward in sorted(index.inwards.values(), key=lambda row: row.order_code):
            if not _in_month(inward.at, year, month_n):
                continue
            label = inward.order_code
            if inward.supplier_name:
                label = f"{inward.order_code} · {inward.supplier_name}"
            options.append(
                AcMaterialTraceOptionOut(
                    code=inward.order_code, kind=wanted, label=label, at=inward.at
                )
            )
    elif wanted == "dispatch":
        for row in sorted(index.dispatches.values(), key=lambda item: item.dispatch_code):
            if not _in_month(row.at, year, month_n):
                continue
            label = row.dispatch_code
            if row.work_order_code:
                label = f"{row.dispatch_code} · {row.work_order_code}"
            options.append(
                AcMaterialTraceOptionOut(
                    code=row.dispatch_code, kind=wanted, label=label, at=row.at
                )
            )
    else:
        for bag_code in sorted(index.bags):
            if not _bag_in_month(index, bag_code, year, month_n):
                continue
            refs = index.bags[bag_code]
            stage = STAGE_LABELS.get(refs[-1].stage, refs[-1].stage)
            options.append(
                AcMaterialTraceOptionOut(
                    code=bag_code,
                    kind=wanted,
                    label=f"{bag_code} · {stage}",
                    at=next((ref.at for ref in reversed(refs) if ref.at), None),
                )
            )
    return AcMaterialTraceOptionsOut(
        kind=wanted,
        month=month_key,
        month_label=month_label,
        options=options,
    )


def lookup_material_trace(
    db: Session, tenant: TenantContext, query: str
) -> AcMaterialTraceOut:
    return resolve_trace(build_trace_index(db, tenant), query)


def list_material_trace_options(
    db: Session, tenant: TenantContext, kind: str, month: str | None = None
) -> AcMaterialTraceOptionsOut:
    return list_trace_options(build_trace_index(db, tenant), kind, month)
