"""Tenant process rules for GR Carbons inbound and destoning gates.

Stored in tenant metadata (ac_process_rules). Not shop-floor capture and does not
replace inward ORD-* or lot triplet subjects.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import Tenant

META_KEY = "ac_process_rules"

SOURCE_BAG_KG = Decimal("25")
REPACK_BAG_KG = Decimal("500")
MOISTURE_DRY_THRESHOLD_PCT = Decimal("20")
CTC_DECIMALS = 1

SAD_PROCESS_KEY = "screening_after_destoning"
SAD_DESTINATION = "Screening after Destoning"
SCREENING_PROCESS_KEY = "screening"
SCREENING_DESTINATION = "Screening"
INSTOCK_DESTINATION = "In Stock"
DESTONING_REWORK_PROCESS_KEY = "destoning"
DESTONING_REWORK_DESTINATION = "Destoning"
STONES_YES = frozenset({"yes", "y", "true", "1", "present", "stone", "stones"})
STONES_NO = frozenset({"no", "n", "false", "0", "absent", "none"})

LAB_PARAM_VOLATILITY = "volatility"
LAB_PARAM_AD_VALUE = "ad_value"
VOLATILITY_URI = "urn:nyra:ac:parameter:VOLATILITY"
AD_VALUE_URI = "urn:nyra:ac:parameter:AD_VALUE"

INITIAL_SCREENING_LABEL = "RMS Screen"
INITIAL_SCREENING_OUTPUT_LABEL = "GRN"

INBOUND_REPACK_CODE = "IN-REPACK"
INBOUND_DRYING_CODE = "IN-DRYING"

# Upper end of the 500 kg bag estimate. A bag inside the range stays in process.
POST_ACTIVATION_OUTPUT_MINUTE_DEFAULTS: dict[str, Optional[float]] = {
    "screening": 20,
    "dedusting": 10,
    "destoning": 15,
    "demagnetisation": 5,
    "material_handling": 10,
    "crushing": None,
    "blending": None,
}
POST_ACTIVATION_OUTPUT_MINUTE_KEYS = tuple(POST_ACTIVATION_OUTPUT_MINUTE_DEFAULTS)


def default_post_activation_output_minutes() -> dict[str, Optional[float]]:
    return dict(POST_ACTIVATION_OUTPUT_MINUTE_DEFAULTS)


def _output_minutes(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def default_process_rules() -> dict[str, Any]:
    return {
        "source_bag_kg": float(SOURCE_BAG_KG),
        "repack_bag_kg": float(REPACK_BAG_KG),
        "moisture_dry_threshold_pct": float(MOISTURE_DRY_THRESHOLD_PCT),
        "ctc_decimals": CTC_DECIMALS,
        "ctc_missing_blocks_load": True,
        "destoning_destinations": [SCREENING_DESTINATION, DESTONING_REWORK_DESTINATION],
        "kiln_feed_qc_required": False,
        "kiln_output_qc_required_for_destoning": True,
        "destoning_qc_required": False,
        "lab_ad_value_capture": False,
        "lab_volatility_capture": True,
        "post_activation_output_minutes": default_post_activation_output_minutes(),
    }


def _tenant_row(db: Session, tenant: TenantContext) -> Tenant:
    row = db.get(Tenant, tenant.tenant_id)
    if row is None:
        row = db.query(Tenant).filter(Tenant.tenant_id == tenant.tenant_id).first()
    if row is None:
        raise ValueError(f"Tenant '{tenant.tenant_code}' not found")
    return row


def plan_rms_bag_weights(total_kg: Any, bag_kg: Any = None) -> list[Decimal]:
    """Split inward weight into 500 kg bags, with a remainder bag if needed."""
    size = _as_decimal(bag_kg, REPACK_BAG_KG)
    try:
        total = Decimal(str(total_kg))
    except (InvalidOperation, TypeError, ValueError):
        total = Decimal("0")
    if total <= 0:
        raise ValidationError("Inward weight must be greater than zero to create RMS bags.")
    weights: list[Decimal] = []
    remaining = total
    while remaining > 0:
        chunk = size if remaining >= size else remaining
        weights.append(chunk)
        remaining -= chunk
    return weights


def _as_decimal(raw: Any, fallback: Decimal) -> Decimal:
    if raw in (None, ""):
        return fallback
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return fallback
    if value <= 0:
        return fallback
    return value


def normalize_process_rules(payload: dict | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    defaults = default_process_rules()
    ctc_decimals = int(data.get("ctc_decimals") if data.get("ctc_decimals") not in (None, "") else CTC_DECIMALS)
    if ctc_decimals < 0 or ctc_decimals > 4:
        raise ValidationError("CTC decimal places must be between 0 and 4.")
    destinations = data.get("destoning_destinations")
    if not isinstance(destinations, list) or not destinations:
        destinations = [SCREENING_DESTINATION, DESTONING_REWORK_DESTINATION]
    skip = {SAD_DESTINATION, INSTOCK_DESTINATION}
    cleaned = [str(row).strip() for row in destinations if str(row).strip() and str(row).strip() not in skip]
    if SCREENING_DESTINATION not in cleaned:
        cleaned = [SCREENING_DESTINATION, *cleaned]
    if DESTONING_REWORK_DESTINATION not in cleaned:
        cleaned.append(DESTONING_REWORK_DESTINATION)
    return {
        "source_bag_kg": float(_as_decimal(data.get("source_bag_kg"), SOURCE_BAG_KG)),
        "repack_bag_kg": float(_as_decimal(data.get("repack_bag_kg"), REPACK_BAG_KG)),
        "moisture_dry_threshold_pct": float(
            _as_decimal(data.get("moisture_dry_threshold_pct"), MOISTURE_DRY_THRESHOLD_PCT)
        ),
        "ctc_decimals": ctc_decimals,
        "ctc_missing_blocks_load": bool(
            data.get("ctc_missing_blocks_load", defaults["ctc_missing_blocks_load"])
        ),
        "destoning_destinations": cleaned,
        "kiln_feed_qc_required": False,
        "kiln_output_qc_required_for_destoning": bool(
            data.get("kiln_output_qc_required_for_destoning", True)
        ),
        "destoning_qc_required": bool(data.get("destoning_qc_required", False)),
        "lab_ad_value_capture": bool(data.get("lab_ad_value_capture", False)),
        "lab_volatility_capture": bool(data.get("lab_volatility_capture", True)),
        "post_activation_output_minutes": _normalize_output_minutes(
            data.get("post_activation_output_minutes")
        ),
    }


def _normalize_output_minutes(raw: Any) -> dict[str, Optional[float]]:
    block = raw if isinstance(raw, dict) else {}
    minutes: dict[str, Optional[float]] = {}
    for key in POST_ACTIVATION_OUTPUT_MINUTE_KEYS:
        if key not in block:
            minutes[key] = POST_ACTIVATION_OUTPUT_MINUTE_DEFAULTS[key]
        else:
            minutes[key] = _output_minutes(block.get(key))
    return minutes


def get_process_rules(db: Session, tenant: TenantContext) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    block = meta.get(META_KEY)
    if not isinstance(block, dict):
        return default_process_rules()
    try:
        return normalize_process_rules(block)
    except ValidationError:
        return default_process_rules()


def save_process_rules(db: Session, tenant: TenantContext, payload: dict) -> dict[str, Any]:
    cleaned = normalize_process_rules(payload)
    row = _tenant_row(db, tenant)
    meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
    meta[META_KEY] = cleaned
    row.metadata_ = meta
    flag_modified(row, "metadata_")
    db.commit()
    db.refresh(row)
    return cleaned


def ensure_process_rules(db: Session, tenant: TenantContext) -> dict[str, Any]:
    row = _tenant_row(db, tenant)
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    if isinstance(meta.get(META_KEY), dict):
        return get_process_rules(db, tenant)
    return save_process_rules(db, tenant, default_process_rules())


def round_ctc(raw: Any, decimals: int = CTC_DECIMALS) -> Optional[Decimal]:
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    quant = Decimal("1") if decimals <= 0 else Decimal("1").scaleb(-decimals)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def ctc_from_values(values: dict | None) -> Any:
    data = values if isinstance(values, dict) else {}
    for key, value in data.items():
        if "ctc" in str(key).lower() and value not in (None, ""):
            return value
    return None


def assert_same_ctc(
    existing_raw: Any,
    incoming_raw: Any,
    *,
    decimals: int = CTC_DECIMALS,
    missing_blocks: bool = True,
) -> Decimal:
    incoming = round_ctc(incoming_raw, decimals)
    if incoming is None:
        raise ValidationError(
            "Kiln output CTC is required before destoning load — save kiln output QC first."
            if missing_blocks
            else "This destoner load cannot mix a blank CTC with a numeric CTC."
        )
    existing = round_ctc(existing_raw, decimals)
    if existing is None:
        return incoming
    if existing != incoming:
        raise ValidationError(
            f"Destoner load must be the same CTC (rounded to {decimals} decimal). "
            f"Loader has {existing}, bag is {incoming}."
        )
    return incoming


def assert_destoner_plan_ctc(
    assigned_raw: Any,
    incoming_raw: Any,
    *,
    decimals: int = CTC_DECIMALS,
) -> Decimal:
    """Supervisor daily CTC is required; kiln-output bag CTC must match it."""
    assigned = round_ctc(assigned_raw, decimals)
    if assigned is None:
        raise ValidationError(
            "Supervisor must set today's CTC for this destoner in Masters before load."
        )
    incoming = round_ctc(incoming_raw, decimals)
    if incoming is None:
        raise ValidationError(
            "Kiln output CTC is required before destoning load — save kiln output QC first."
        )
    if assigned != incoming:
        raise ValidationError(
            f"This destoner is set for CTC {assigned} today. Bag CTC is {incoming}."
        )
    return incoming


def destoning_stones_from_values(values: dict | None) -> Any:
    data = values if isinstance(values, dict) else {}
    for key in ("deston_qc_stones", "has_stones", "stones"):
        if data.get(key) not in (None, ""):
            return data.get(key)
    for key, value in data.items():
        if "stone" in str(key).lower() and value not in (None, ""):
            return value
    return None


def destoning_stones_present(raw: Any) -> Optional[bool]:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text in STONES_YES:
        return True
    if text in STONES_NO:
        return False
    try:
        return Decimal(text) > 0
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("Destoning quality must be Yes or No for stones.")


def destoning_destination_from_stones(raw: Any) -> str:
    present = destoning_stones_present(raw)
    if present is None:
        raise ValidationError("Say whether stones are present.")
    return DESTONING_REWORK_DESTINATION if present else SCREENING_DESTINATION


def is_destoning_rework_destination(raw: Any) -> bool:
    text = str(raw or "").strip().lower()
    if not text:
        return False
    collapsed = " ".join("".join(ch if ch.isalnum() else " " for ch in text).split())
    return collapsed in {"destoning", "destone", "destone again", "destoning again"}


def moisture_requires_drying(moisture_pct: Any, threshold_pct: Any = MOISTURE_DRY_THRESHOLD_PCT) -> bool:
    if moisture_pct in (None, ""):
        return False
    try:
        value = Decimal(str(moisture_pct))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return value > Decimal(str(threshold_pct))


def latest_moisture_pct(meta: dict | None) -> Optional[Decimal]:
    """Prefer Initial Screening moisture; else latest 500 kg bag lab; else inward lab."""
    data = meta if isinstance(meta, dict) else {}
    crush = data.get("crusher_output") if isinstance(data.get("crusher_output"), dict) else {}
    if crush.get("moisture_pct") not in (None, ""):
        try:
            return Decimal(str(crush.get("moisture_pct")))
        except (InvalidOperation, TypeError, ValueError):
            pass
    bags = data.get("inward_bags") if isinstance(data.get("inward_bags"), list) else []
    readings: list[Decimal] = []
    for bag in bags:
        if not isinstance(bag, dict):
            continue
        lab = bag.get("lab_qc") if isinstance(bag.get("lab_qc"), dict) else {}
        raw = lab.get("moisture_pct")
        if raw in (None, ""):
            continue
        try:
            readings.append(Decimal(str(raw)))
        except (InvalidOperation, TypeError, ValueError):
            continue
    if readings:
        return max(readings)
    initial = data.get("initial_qc") if isinstance(data.get("initial_qc"), dict) else {}
    if initial.get("moisture_pct") not in (None, ""):
        try:
            return Decimal(str(initial.get("moisture_pct")))
        except (InvalidOperation, TypeError, ValueError):
            return None
    exec_map = data.get("inbound_execution") if isinstance(data.get("inbound_execution"), dict) else {}
    lab_exec = exec_map.get("IN-LAB") if isinstance(exec_map.get("IN-LAB"), dict) else {}
    if lab_exec.get("moisture_pct") not in (None, ""):
        try:
            return Decimal(str(lab_exec.get("moisture_pct")))
        except (InvalidOperation, TypeError, ValueError):
            return None
    return None


def drying_completed(meta: dict | None) -> bool:
    data = meta if isinstance(meta, dict) else {}
    exec_map = data.get("inbound_execution") if isinstance(data.get("inbound_execution"), dict) else {}
    row = exec_map.get(INBOUND_DRYING_CODE)
    if isinstance(row, dict) and str(row.get("status") or "").upper() == "COMPLETED":
        return True
    drying = data.get("drying") if isinstance(data.get("drying"), dict) else {}
    return str(drying.get("status") or "").upper() == "COMPLETED"


def assert_drying_before_kiln(meta: dict | None, rules: dict | None = None) -> None:
    cfg = rules if isinstance(rules, dict) else default_process_rules()
    moisture = latest_moisture_pct(meta)
    threshold = cfg.get("moisture_dry_threshold_pct", float(MOISTURE_DRY_THRESHOLD_PCT))
    if not moisture_requires_drying(moisture, threshold):
        return
    if drying_completed(meta):
        return
    raise ValidationError(
        f"Moisture {moisture} % is above {threshold} % — complete Drying before kiln feed."
    )


def _op_dict(op: Any) -> dict:
    if isinstance(op, dict):
        return dict(op)
    if hasattr(op, "model_dump"):
        return op.model_dump()
    return dict(op)


DEFAULT_INBOUND_OPERATIONS = [
    {
        "operation_code": "IN-RMS-BAG",
        "operation_name": "Bag split",
        "process_step": "PACKING",
        "is_mandatory": True,
    },
    {
        "operation_code": "IN-LAB",
        "operation_name": "Lab — moisture, dust, volatility (approve/deny)",
        "process_step": "SCREENING",
        "is_mandatory": True,
    },
    {
        "operation_code": "IN-RM-OUT",
        "operation_name": INITIAL_SCREENING_OUTPUT_LABEL,
        "process_step": "SCREENING",
        "is_mandatory": True,
    },
]


def is_kiln_feed_bag_qc_step(op: Any) -> bool:
    """Retired Execution / Masters step: Kiln Feed Bag Quantity (quality)."""
    row = _op_dict(op)
    code = str(row.get("operation_code") or "").strip().upper().replace("-", "_")
    name = str(row.get("operation_name") or "").strip().lower()
    if code in {
        "OP_KILN_FEED_QC",
        "KILN_FEED_QC",
        "OP_KILN_FEED_BAG_QC",
        "OP_KILN_FEED_BAG_QTY",
        "OP_KILN_FEED_BAG_QUANTITY",
    }:
        return True
    if "KILN" in code and "FEED" in code and (
        "QC" in code or "QUALITY" in code or "BAG_QTY" in code or "BAG_QUANTITY" in code
    ):
        return True
    if "kiln feed" not in name:
        return False
    return (
        "quality" in name
        or " qc" in name
        or name.endswith(" qc")
        or "bag quantity" in name
        or "bag qty" in name
    )


def is_kiln_feed_bag_qc_parameter(row: Any) -> bool:
    param = _op_dict(row)
    code = str(param.get("operation_code") or "").strip().upper()
    if is_kiln_feed_bag_qc_step({"operation_code": code}):
        return True
    key = str(param.get("key") or param.get("parameter_code") or "").strip().lower()
    return key.startswith("kfqc_") or key.startswith("feed_qc_")


def without_kiln_feed_bag_qc_operations(ops: list | None) -> list[dict]:
    return [_op_dict(op) for op in (ops or []) if not is_kiln_feed_bag_qc_step(op)]


def without_kiln_feed_bag_qc_parameters(params: list | None) -> list[dict]:
    return [_op_dict(row) for row in (params or []) if not is_kiln_feed_bag_qc_parameter(row)]


def looks_like_full_inbound_catalog(ops: list) -> bool:
    codes = {
        str((_op_dict(op).get("operation_code") or "")).strip().upper()
        for op in (ops or [])
    }
    if not codes:
        return True
    return bool(
        codes
        & {"IN-CRUSHER", "IN-RM-OUT", "IN-RMS-BAG", "IN-LAB", INBOUND_REPACK_CODE, INBOUND_DRYING_CODE}
    )


def normalized_inbound_operations(ops: list | None) -> list[dict]:
    """Shop-floor inbound: Bag split (IN-RMS-BAG) → Lab (IN-LAB) → RMS Outward → release."""
    rows = [_op_dict(op) for op in (ops or [])]
    if not looks_like_full_inbound_catalog(rows):
        return sorted(rows, key=lambda o: int(o.get("operation_sequence") or 0))

    by_code: dict[str, dict] = {}
    for row in rows:
        code = str(row.get("operation_code") or "").strip().upper()
        if not code:
            continue
        if code == "IN-RM-OUT":
            row["operation_name"] = INITIAL_SCREENING_OUTPUT_LABEL
        elif code == "IN-RMS-BAG":
            row["operation_name"] = "Bag split"
        elif code == "IN-LAB":
            row["operation_name"] = "Lab — moisture, dust, volatility (approve/deny)"
        by_code[code] = row

    for default in DEFAULT_INBOUND_OPERATIONS:
        code = default["operation_code"]
        if code not in by_code:
            by_code[code] = dict(default)

    sequence = ["IN-RMS-BAG", "IN-LAB", "IN-RM-OUT"]
    skip = {INBOUND_REPACK_CODE, INBOUND_DRYING_CODE, "IN-CRUSHER"}
    ordered: list[dict] = []
    used: set[str] = set()
    seq = 1
    for code in sequence:
        row = by_code.get(code)
        if not row:
            continue
        next_row = dict(row)
        next_row["operation_sequence"] = seq
        next_row["is_mandatory"] = True
        ordered.append(next_row)
        used.add(code)
        seq += 1
    for row in rows:
        code = str(row.get("operation_code") or "").strip().upper()
        if not code or code in used or code in skip:
            continue
        next_row = dict(by_code.get(code) or row)
        next_row["operation_sequence"] = seq
        ordered.append(next_row)
        used.add(code)
        seq += 1
    return ordered


def ensure_inbound_catalog(db: Session, tenant: TenantContext) -> None:
    """Persist Initial Screening labels, repack, drying, and volatility on RM types."""
    from app.models.mes_core import Product

    repo_rows = (
        db.query(Product)
        .filter(Product.tenant_id == tenant.tenant_id)
        .all()
    )
    dirty = False
    for product in repo_rows:
        meta = dict(product.metadata_ if isinstance(product.metadata_, dict) else {})
        ops = meta.get("inbound_operations")
        if not isinstance(ops, list):
            ops = []
        if ops and not looks_like_full_inbound_catalog(ops):
            continue
        next_ops = normalized_inbound_operations(ops)
        params = list(meta.get("process_parameters") or [])
        has_volatility = any(
            str(row.get("key") or row.get("parameter_code") or "").lower() == LAB_PARAM_VOLATILITY
            for row in params
            if isinstance(row, dict)
        )
        if not has_volatility:
            params.append(
                {
                    "key": LAB_PARAM_VOLATILITY,
                    "label": "Volatility",
                    "unit": "%",
                    "process_step": "SCREENING",
                    "used_at": "inbound",
                    "operation_code": "IN-LAB",
                    "object_uri": VOLATILITY_URI,
                    "is_mandatory": True,
                }
            )
        if next_ops != ops or params != (meta.get("process_parameters") or []):
            meta["inbound_operations"] = next_ops
            meta["process_parameters"] = params
            product.metadata_ = meta
            flag_modified(product, "metadata_")
            dirty = True
    if dirty:
        db.commit()
