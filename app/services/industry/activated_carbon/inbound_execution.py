"""Configurable inbound prep execution (Lab → RMS bags → crusher → RM outward)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.transaction import CustomerOrder
from app.schemas.mes_core.schemas import (
    AcInboundStepCompleteCreate,
    AcInboundStepStatusOut,
    AcRawMaterialTypeOut,
    TripleCreate,
)
from app.services.industry.activated_carbon.raw_material_types import get_raw_material_type
from app.services.industry.activated_carbon import inbound_admin as ac_inbound_admin
from app.services.industry.activated_carbon import inbound_workflow as ac_inbound_workflow
from app.services.industry.activated_carbon import triplet_capture
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.base import TenantRepository

INBOUND_STEP_OBJECT_URI = {
    "CRUSHING": "urn:nyra:ac:crushing:{order_code}",
    "DRYING": "urn:nyra:ac:drying:{order_code}",
    "GRINDING": "urn:nyra:ac:grinding:{order_code}",
    "DESTONING": "urn:nyra:ac:destoning:{order_code}",
    "SCREENING": "urn:nyra:ac:inboundScreening:{order_code}",
    "PACKING": "urn:nyra:ac:packing:{order_code}",
}


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _normalize_step(step: str) -> str:
    return (step or "").strip().upper()


def _json_val(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def resolve_inbound_operations(material_type: AcRawMaterialTypeOut) -> list[dict]:
    ops = material_type.inbound_operations or []
    return sorted(
        [dict(op) if isinstance(op, dict) else op.model_dump() for op in ops],
        key=lambda o: int(o.get("operation_sequence") or 0),
    )


def _step_storage_key(op: dict) -> str:
    code = (op.get("operation_code") or "").strip().upper()
    if code:
        return code
    return _normalize_step(op.get("process_step") or "")


def _legacy_crush_record(meta: dict) -> dict:
    crush = meta.get("raw_material_crush")
    return crush if isinstance(crush, dict) else {}


def _inbound_execution_map(meta: dict) -> dict:
    raw = meta.get("inbound_execution")
    return dict(raw) if isinstance(raw, dict) else {}


def _step_record(meta: dict, op: dict) -> dict:
    exec_map = _inbound_execution_map(meta)
    key = _step_storage_key(op)
    row = exec_map.get(key)
    if isinstance(row, dict) and row:
        return row
    step = _normalize_step(op.get("process_step") or "")
    legacy = exec_map.get(step)
    if isinstance(legacy, dict) and legacy:
        return legacy
    if step == "CRUSHING" and _legacy_crush_record(meta):
        return _legacy_crush_record(meta)
    return {}


def _is_lab_operation(op: dict) -> bool:
    code = str(op.get("operation_code") or "").strip().upper()
    return code == "IN-LAB" or code.startswith("IN-LAB")


def inbound_step_completed(meta: dict, op: dict) -> bool:
    if ac_inbound_workflow.lab_denied(meta) and _is_lab_operation(op):
        return False
    row = _step_record(meta, op)
    return str(row.get("status") or "").upper() == "COMPLETED"


def _step_status_row(
    op: dict,
    meta: dict,
) -> AcInboundStepStatusOut:
    step = _normalize_step(op.get("process_step") or "")
    row = _step_record(meta, op)
    status = str(row.get("status") or "PENDING").upper()
    if ac_inbound_workflow.lab_denied(meta) and _is_lab_operation(op):
        status = "DENIED"
    completed_at = row.get("completed_at")
    return AcInboundStepStatusOut(
        process_step=step,
        operation_name=op.get("operation_name") or step,
        operation_code=op.get("operation_code"),
        is_mandatory=op.get("is_mandatory", True),
        status=status,
        completed_at=completed_at,
    )


def build_inbound_step_statuses(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
) -> list[AcInboundStepStatusOut]:
    return [_step_status_row(op, meta) for op in resolve_inbound_operations(material_type)]


def mandatory_inbound_prep_complete(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
) -> bool:
    if ac_inbound_workflow.lab_denied(meta):
        return False
    for op in resolve_inbound_operations(material_type):
        if not op.get("is_mandatory", True):
            continue
        if not inbound_step_completed(meta, op):
            return False
    return True


def next_inbound_operation(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
) -> Optional[dict]:
    if ac_inbound_workflow.lab_denied(meta):
        return None
    for op in resolve_inbound_operations(material_type):
        if not inbound_step_completed(meta, op):
            return op
    return None


def next_inbound_process_step(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
) -> Optional[str]:
    op = next_inbound_operation(material_type, meta)
    if not op:
        return None
    return _normalize_step(op.get("process_step") or "")


def next_inbound_operation_code(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
) -> Optional[str]:
    op = next_inbound_operation(material_type, meta)
    if not op:
        return None
    return op.get("operation_code")


def assert_prior_inbound_steps_complete(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
    target_op: dict,
) -> None:
    if ac_inbound_workflow.lab_denied(meta) and not _is_lab_operation(target_op):
        raise ValidationError(
            "Lab denied this inward — it will not proceed to RMS, crusher, outward, or release."
        )
    target_key = _step_storage_key(target_op)
    for op in resolve_inbound_operations(material_type):
        if _step_storage_key(op) == target_key:
            return
        if not inbound_step_completed(meta, op):
            label = op.get("operation_name") or op.get("process_step")
            raise ValidationError(
                f"Complete inbound step '{label}' before this step."
            )
    raise ValidationError(
        f"Inbound step '{target_op.get('operation_name')}' is not configured for this material."
    )


def _resolve_target_op(
    material_type: AcRawMaterialTypeOut,
    meta: dict,
    payload: AcInboundStepCompleteCreate,
) -> dict:
    ops = resolve_inbound_operations(material_type)
    if not ops:
        raise ValidationError("No inbound prep steps configured for this raw material type.")

    code = (payload.operation_code or "").strip().upper()
    if code:
        for op in ops:
            if (op.get("operation_code") or "").strip().upper() == code:
                return op
        raise ValidationError(f"Unknown inbound operation code '{payload.operation_code}'.")

    step = _normalize_step(payload.process_step)
    matches = [
        op
        for op in ops
        if _normalize_step(op.get("process_step") or "") == step
        and not inbound_step_completed(meta, op)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValidationError(
            f"Multiple inbound steps use process_step '{step}' — send operation_code "
            f"(e.g. {matches[0].get('operation_code')})."
        )
    for op in ops:
        if _normalize_step(op.get("process_step") or "") == step:
            return op
    raise ValidationError(
        f"Process step '{payload.process_step}' is not configured for this raw material type."
    )


def _stage_inbound_step_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    process_step: str,
    payload: dict,
    material_type=None,
    *,
    operation_code: Optional[str] = None,
) -> None:
    step = _normalize_step(process_step)
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    object_template = INBOUND_STEP_OBJECT_URI.get(
        step, "urn:nyra:ac:inboundStep:{step}:{order_code}"
    )
    object_uri = object_template.format(step=step, order_code=order.order_code)
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:captures",
            object_uri=object_uri,
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    if material_type is not None:
        triplet_capture.stage_inbound_step_captures(
            db,
            tenant,
            order,
            step,
            payload,
            material_type,
            operation_code=operation_code,
        )
        return
    triplet_capture.stage_captures_for_values(
        db,
        tenant,
        subject_uri=subject,
        values=payload,
        source_table="trn.customer_order",
        source_id=source_id,
        process_step=step,
        used_at="inbound",
        operation_code=operation_code,
    )


def _material_type_for_order(
    db: Session, tenant: TenantContext, order: CustomerOrder, product_id: UUID
) -> AcRawMaterialTypeOut:
    try:
        return get_raw_material_type(db, tenant, product_id)
    except NotFoundError as exc:
        raise ValidationError(
            "Raw material type for this inward receipt is not configured in Masters."
        ) from exc


def _apply_step_domain_rules(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    meta: dict,
    target_op: dict,
    params: dict,
) -> None:
    code = (target_op.get("operation_code") or "").strip().upper()
    if _is_lab_operation(target_op):
        decision = str(params.get("qc_decision") or params.get("qc_status") or "").upper()
        remarks = str(
            params.get("qc_remarks")
            or params.get("remarks")
            or params.get("operator_remarks")
            or ""
        ).strip()
        mapped = "PASS" if decision in ("APPROVE", "APPROVED", "PASS", "") else decision
        if mapped in ("DENY", "REJECT"):
            mapped = "FAIL"
        if mapped == "FAIL" and not remarks:
            raise ValidationError(
                "Enter remarks when denying this inward. The record will stop here."
            )
        meta["initial_qc"] = {
            "qc_status": mapped,
            "moisture_pct": params.get("moisture_pct"),
            "dust_pct": params.get("dust_pct"),
            "ad_value": params.get("ad_value"),
            "remarks": remarks or None,
            "qc_at": datetime.now(timezone.utc).isoformat(),
            "source": "inbound_execution_lab",
        }
        if mapped == "FAIL":
            meta["inbound_lab_denied"] = True
            meta.setdefault("raw_material_qc", {})
            if isinstance(meta["raw_material_qc"], dict):
                meta["raw_material_qc"] = {
                    **meta["raw_material_qc"],
                    "qc_status": "QC_FAILED",
                    "operator_remarks": remarks,
                    "qc_at": meta["initial_qc"]["qc_at"],
                    "source": "inbound_execution_lab_deny",
                }
            order.status = "QC_FAILED"
        else:
            meta["inbound_lab_denied"] = False
        return

    if code == "IN-RMS-BAG":
        _, received_kg = ac_inbound_workflow._require_inward_order(
            db, tenant, order.customer_order_id
        )
        bags = ac_inbound_workflow._rms_bags(meta)
        if not bags:
            raise ValidationError("Create RMS bags before completing RMS inward.")
        total_kg = sum(Decimal(str(row.get("weight_kg") or 0)) for row in bags)
        variance_kg = received_kg - total_kg
        remark = str(params.get("variance_comment") or params.get("remarks") or "").strip()
        if total_kg > received_kg + Decimal("0.01"):
            raise ValidationError(
                f"RMS bag total {total_kg} KG exceeds inward weight {received_kg} KG."
            )
        if variance_kg > Decimal("0.01") and not remark:
            raise ValidationError(
                f"RMS bag total {total_kg} KG is less than inward weight {received_kg} KG — enter remarks."
            )
        meta["bag_reconciliation"] = {
            "status": "RECONCILED",
            "total_kg": str(total_kg),
            "received_kg": str(received_kg),
            "variance_kg": str(variance_kg),
            "variance_comment": remark or None,
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
        }
        return

    if code == "IN-CRUSHER":
        if not ac_inbound_workflow.all_bags_fed_to_crusher(meta):
            raise ValidationError("Feed every RMS bag to the crusher before recording performance.")
        rotary = str(params.get("rotary") or "").strip()
        allowed = ac_inbound_admin.rotary_names(db, tenant)
        if rotary not in allowed:
            raise ValidationError(f"Select a rotary from plant settings: {', '.join(allowed)}")
        grade = (params.get("crusher_grade") or "").strip() or None
        if not grade:
            params.pop("crusher_grade", None)
        dust = params.get("dust_pct") if params.get("dust_pct") not in (None, "") else params.get(
            "dust_generation_pct"
        )
        moisture = (
            params.get("moisture_pct")
            if params.get("moisture_pct") not in (None, "")
            else params.get("moisture_after_crush_pct")
        )
        if dust in (None, "") or moisture in (None, ""):
            raise ValidationError("Enter dust (%) and moisture (%).")
        crusher_output = {
            "rotary": rotary,
            "dust_pct": dust,
            "moisture_pct": moisture,
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if grade:
            crusher_output["crusher_grade"] = grade
        for field, label, _uri in ac_inbound_workflow.MESH_PCT_FIELDS:
            raw = params.get(field)
            if raw in (None, ""):
                params.pop(field, None)
                continue
            try:
                pct = Decimal(str(raw))
            except Exception:
                raise ValidationError(f"{label} must be a number (%).")
            if pct < 0 or pct > 100:
                raise ValidationError(f"{label} must be between 0 and 100 %.")
            crusher_output[field] = str(pct)
            params[field] = str(pct)
        meta["crusher_output"] = crusher_output
        return

    if code == "IN-RM-OUT":
        splits = params.get("outward_splits") or params.get("grade_splits") or []
        rotaries = ac_inbound_admin.rotary_names(db, tenant)
        cleaned = []
        for row in splits:
            if not isinstance(row, dict):
                continue
            label = str(row.get("grade_label") or row.get("label") or "").strip()
            rotary = str(row.get("rotary") or "").strip()
            qty = row.get("quantity_kg") or row.get("weight_kg")
            bag_code = row.get("bag_code")
            if not label or qty in (None, ""):
                continue
            if not ac_inbound_admin.is_allowed_outward_grade(db, tenant, label):
                raise ValidationError(f"Unknown outward split '{label}'.")
            if rotary and rotary not in rotaries:
                raise ValidationError(f"Unknown rotary '{rotary}'.")
            cleaned.append(
                {
                    "grade_label": ac_inbound_admin._canonical_outward_grade(label),
                    "rotary": rotary or None,
                    "quantity_kg": str(qty),
                    "bag_code": bag_code,
                }
            )
        if not cleaned:
            raise ValidationError("Enter RM outward split weights and bags.")
        ac_inbound_admin.validate_rm_outward_splits(cleaned)
        _, received_kg = ac_inbound_workflow._require_inward_order(
            db, tenant, order.customer_order_id
        )
        outward_total = sum(Decimal(str(row.get("quantity_kg") or 0)) for row in cleaned)
        ac_inbound_admin.validate_outward_kg_within_inward(outward_total, received_kg)
        meta["grade_separation"] = {
            "status": "COMPLETED",
            "grade_splits": cleaned,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        meta.setdefault("raw_material_qc", {})
        if isinstance(meta["raw_material_qc"], dict):
            meta["raw_material_qc"] = {
                **meta["raw_material_qc"],
                "qc_status": "QC_PASSED",
                "qc_at": datetime.now(timezone.utc).isoformat(),
                "source": "inbound_prep_complete",
            }
        order.status = "QC_PASSED"


def complete_inbound_step(
    db: Session,
    tenant: TenantContext,
    payload: AcInboundStepCompleteCreate,
    *,
    product_id: UUID,
    allow_unconfigured: bool = False,
) -> dict:
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, payload.customer_order_id
    )
    meta = dict(order.metadata_ if isinstance(order.metadata_, dict) else {})
    material_type = _material_type_for_order(db, tenant, order, product_id)

    try:
        target_op = _resolve_target_op(material_type, meta, payload)
    except ValidationError:
        if allow_unconfigured:
            target_op = {
                "operation_code": payload.operation_code or payload.process_step,
                "process_step": payload.process_step,
                "operation_name": payload.process_step,
            }
        else:
            raise

    step = _normalize_step(target_op.get("process_step") or payload.process_step)
    storage_key = _step_storage_key(target_op)

    prior_status = str(_step_record(meta, target_op).get("status") or "").upper()
    if prior_status in ("COMPLETED", "DENIED"):
        raise ValidationError(
            f"Order '{order.order_code}' — step '{target_op.get('operation_name')}' is already recorded."
        )

    assert_prior_inbound_steps_complete(material_type, meta, target_op)

    params = dict(payload.parameters or {})
    _apply_step_domain_rules(db, tenant, order, meta, target_op, params)
    now_iso = datetime.now(timezone.utc).isoformat()
    denied = _is_lab_operation(target_op) and ac_inbound_workflow.lab_denied(meta)
    record = {
        k: _json_val(v)
        for k, v in {
            **params,
            "status": "DENIED" if denied else "COMPLETED",
            "completed_at": now_iso,
            "process_step": step,
            "operation_code": target_op.get("operation_code"),
        }.items()
        if v is not None
    }

    exec_map = _inbound_execution_map(meta)
    exec_map[storage_key] = record
    meta["inbound_execution"] = exec_map

    if step == "CRUSHING":
        meta["raw_material_crush"] = {
            k: v
            for k, v in record.items()
            if k not in ("process_step", "operation_code")
        }

    order.metadata_ = meta
    flag_modified(order, "metadata_")
    _stage_inbound_step_triples(
        db,
        tenant,
        order,
        step,
        params,
        material_type,
        operation_code=target_op.get("operation_code"),
    )
    repo.db.commit()
    repo.db.refresh(order)
    return {
        "order": order,
        "material_type": material_type,
        "meta": meta,
        "completed_step": step,
        "completed_operation_code": target_op.get("operation_code"),
    }
