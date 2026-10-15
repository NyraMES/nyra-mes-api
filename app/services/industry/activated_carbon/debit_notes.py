"""Supplier debit note on inward.

Raised when our weight is short of supplier weight (from gate) or moisture
is above the plant threshold (after lab). Value is entered by the user.
Optional — does not block RMS Outward. Stored on inward metadata; subject
stays urn:nyra:ac:inward:{ORD-AC-*}.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import CustomerOrder, Supplier
from app.schemas.mes_core.schemas import AcDebitNoteCreate, AcDebitNoteOut, TripleCreate
from app.services.industry.activated_carbon import inbound_workflow as ac_inbound_workflow
from app.services.industry.activated_carbon import process_rules as ac_process_rules
from app.services.industry.activated_carbon.codes import resolve_ac_business_code
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.base import TenantRepository

REASON_WEIGHT = "weight_short"
REASON_MOISTURE = "moisture_high"
REASON_LABELS = {
    REASON_WEIGHT: "Our weight is less than supplier weight",
    REASON_MOISTURE: "Moisture is above the plant threshold",
}


def _dec(value: object) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _lab_complete(meta: dict) -> bool:
    if ac_inbound_workflow.lab_denied(meta):
        return False
    initial = ac_inbound_workflow._initial_qc(meta)
    status = str(initial.get("qc_status") or "").upper()
    if status and status not in {"PENDING", "FAIL", "FAILED", "DENIED"}:
        return True
    exec_map = meta.get("inbound_execution") if isinstance(meta.get("inbound_execution"), dict) else {}
    lab = exec_map.get("IN-LAB") if isinstance(exec_map.get("IN-LAB"), dict) else {}
    return str(lab.get("status") or "").upper() == "COMPLETED"


def evaluate_debit_note(
    meta: dict | None,
    rules: dict | None = None,
    *,
    our_weight_fallback: object = None,
    supplier_name: str | None = None,
    supplier_code: str | None = None,
) -> AcDebitNoteOut:
    data = meta if isinstance(meta, dict) else {}
    cfg = rules if isinstance(rules, dict) else ac_process_rules.default_process_rules()
    receipt = ac_inbound_workflow._inward_receipt(data)
    supplier_kg = _dec(receipt.get("supplier_weight_kg"))
    our_kg = _dec(receipt.get("our_weight_kg")) or _dec(our_weight_fallback)
    shortage = (
        supplier_kg - our_kg
        if supplier_kg is not None and our_kg is not None
        else None
    )
    weight_short = shortage is not None and shortage > 0
    moisture = ac_process_rules.latest_moisture_pct(data)
    threshold = _dec(cfg.get("moisture_dry_threshold_pct")) or Decimal(
        str(ac_process_rules.MOISTURE_DRY_THRESHOLD_PCT)
    )
    moisture_high = ac_process_rules.moisture_requires_drying(moisture, threshold)
    lab_complete = _lab_complete(data)
    saved = data.get("debit_note") if isinstance(data.get("debit_note"), dict) else {}
    reasons: list[str] = []
    if weight_short:
        reasons.append(REASON_WEIGHT)
    if moisture_high:
        reasons.append(REASON_MOISTURE)
    eligible = bool(reasons) and lab_complete and not saved.get("debit_note_code")
    if ac_inbound_workflow.lab_denied(data):
        eligible = False
    return AcDebitNoteOut(
        eligible=eligible,
        raised=bool(saved.get("debit_note_code")),
        lab_complete=lab_complete,
        weight_short=weight_short,
        moisture_high=moisture_high,
        supplier_weight_kg=supplier_kg,
        our_weight_kg=our_kg,
        shortage_kg=shortage if weight_short else None,
        moisture_pct=moisture,
        moisture_threshold_pct=threshold,
        debit_note_code=saved.get("debit_note_code"),
        debit_note_value=_dec(saved.get("debit_note_value")),
        remarks=saved.get("remarks"),
        reasons=list(saved.get("reasons") or reasons),
        raised_at=saved.get("raised_at"),
        raised_by=saved.get("raised_by"),
        supplier_code=saved.get("supplier_code") or supplier_code,
        supplier_name=saved.get("supplier_name") or supplier_name,
    )


def raise_debit_note(
    db: Session,
    tenant: TenantContext,
    customer_order_id: UUID,
    payload: AcDebitNoteCreate,
    *,
    raised_by: str | None = None,
) -> AcDebitNoteOut:
    repo = TenantRepository(db, tenant)
    order = repo.get_by_pk(CustomerOrder, CustomerOrder.customer_order_id, customer_order_id)
    meta = dict(order.metadata_ if isinstance(order.metadata_, dict) else {})
    rules = ac_process_rules.get_process_rules(db, tenant)
    supplier = _supplier_for_order(repo, order)
    current = evaluate_debit_note(
        meta,
        rules,
        supplier_name=getattr(supplier, "supplier_name", None),
        supplier_code=getattr(supplier, "supplier_code", None),
    )
    if current.raised:
        raise ValidationError(
            f"Debit note {current.debit_note_code} is already raised on {order.order_code}."
        )
    if ac_inbound_workflow.lab_denied(meta):
        raise ValidationError("A denied inward cannot raise a debit note.")
    if not current.reasons:
        raise ValidationError(
            "A debit note is only for short weight or moisture above the plant threshold."
        )
    if not current.lab_complete:
        raise ValidationError("Complete lab QC before raising a debit note.")
    value = payload.debit_note_value
    if value is None or value <= 0:
        raise ValidationError("Enter the debit note value.")
    code = resolve_ac_business_code(
        db, provided=None, entity="ac_debit_note", tenant_id=tenant.tenant_id
    )
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "debit_note_code": code,
        "debit_note_value": str(value),
        "remarks": (payload.remarks or "").strip() or None,
        "reasons": current.reasons,
        "supplier_weight_kg": str(current.supplier_weight_kg)
        if current.supplier_weight_kg is not None
        else None,
        "our_weight_kg": str(current.our_weight_kg) if current.our_weight_kg is not None else None,
        "shortage_kg": str(current.shortage_kg) if current.shortage_kg is not None else None,
        "moisture_pct": str(current.moisture_pct) if current.moisture_pct is not None else None,
        "moisture_threshold_pct": str(current.moisture_threshold_pct)
        if current.moisture_threshold_pct is not None
        else None,
        "raised_at": now,
        "raised_by": raised_by,
        "supplier_code": current.supplier_code,
        "supplier_name": current.supplier_name,
    }
    meta["debit_note"] = row
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=f"urn:nyra:ac:inward:{order.order_code}",
            predicate_uri="urn:nyra:predicate:captures",
            object_uri=f"urn:nyra:ac:debitNote:{code}",
            object_literal=str(value),
            object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
            source_table="trn.customer_order",
            source_id=order.customer_order_id,
        ),
    )
    repo.db.commit()
    repo.db.refresh(order)
    return evaluate_debit_note(
        order.metadata_ if isinstance(order.metadata_, dict) else {},
        rules,
        supplier_name=current.supplier_name,
        supplier_code=current.supplier_code,
    )


def _supplier_for_order(repo: TenantRepository, order: CustomerOrder) -> Optional[Supplier]:
    if not getattr(order, "supplier_id", None):
        return None
    try:
        return repo.get_by_pk(Supplier, Supplier.supplier_id, order.supplier_id)
    except NotFoundError:
        return None
