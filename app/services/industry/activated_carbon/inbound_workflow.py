"""Post-inward shop-floor workflow: initial QC → bag split → crusher output."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import CustomerOrder, CustomerOrderLine, Product
from app.schemas.mes_core.schemas import (
    AcCrusherOutputCreate,
    AcCrusherOutputOut,
    AcInboundWorkflowOut,
    AcInitialQcCreate,
    AcInitialQcOut,
    AcInwardBagCreate,
    AcInwardBagOut,
    AcInwardBagReconcileCreate,
    AcInwardGradeSeparationCreate,
    AcWeightToCrusherCreate,
    TripleCreate,
)
from app.services.industry.activated_carbon import inbound_admin as ac_inbound_admin
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.base import TenantRepository

BAG_GRADES = (
    "-20 1st Stage - Rotary A",
    "Grade 1st stage - Rotary A",
    "-20 2nd Stage - Rotary B",
    "Grade 2nd stage - Rotary B",
    "Stones",
    "Unburnt",
)

ROTARY_OPTIONS = ("Rotary A", "Rotary B")

MESH_GRADE_FIELDS = (
    ("mesh_plus_2_kg", "+2", "MESH_PLUS_2_KG"),
    ("mesh_2_3_kg", "2/3", "MESH_2_3_KG"),
    ("mesh_3_4_kg", "3/4", "MESH_3_4_KG"),
    ("mesh_4_6_kg", "4/6", "MESH_4_6_KG"),
    ("mesh_6_10_kg", "6/10", "MESH_6_10_KG"),
    ("mesh_10_12_kg", "10/12", "MESH_10_12_KG"),
    ("mesh_12_14_kg", "12/14", "MESH_12_14_KG"),
    ("mesh_minus_14_kg", "-14", "MESH_MINUS_14_KG"),
)

MESH_PCT_FIELDS = (
    ("mesh_plus_2_pct", "+2", "MESH_PLUS_2_PCT"),
    ("mesh_2_3_pct", "2/3", "MESH_2_3_PCT"),
    ("mesh_3_4_pct", "3/4", "MESH_3_4_PCT"),
    ("mesh_4_6_pct", "4/6", "MESH_4_6_PCT"),
    ("mesh_6_10_pct", "6/10", "MESH_6_10_PCT"),
    ("mesh_10_12_pct", "10/12", "MESH_10_12_PCT"),
    ("mesh_12_14_pct", "12/14", "MESH_12_14_PCT"),
    ("mesh_minus_14_pct", "-14", "MESH_MINUS_14_PCT"),
)


def _crusher_scrap_from_output(crusher: dict) -> list[dict]:
    rows: list[dict] = []
    for field, label, _param in MESH_GRADE_FIELDS:
        raw = crusher.get(field)
        if raw is None:
            continue
        qty = Decimal(str(raw))
        if qty <= 0:
            continue
        rows.append(
            {
                "grade_label": label,
                "parameter_key": field,
                "quantity_kg": str(qty),
            }
        )
    return rows


def _grade_param_key(grade_label: str) -> str:
    for idx, grade in enumerate(BAG_GRADES):
        if grade == grade_label:
            return f"separation_grade_{idx + 1}"
    slug = grade_label.upper().replace(" ", "_").replace("-", "_")
    return f"separation_grade_{slug}"


def _separation_grades_from_block(separation: dict) -> list[dict]:
    rows: list[dict] = []
    for entry in separation.get("grade_splits") or []:
        if not isinstance(entry, dict):
            continue
        grade = (entry.get("grade_label") or "").strip()
        qty_raw = entry.get("quantity_kg")
        if not grade or qty_raw is None:
            continue
        qty = Decimal(str(qty_raw))
        if qty <= 0:
            continue
        rows.append(
            {
                "grade_label": grade,
                "parameter_key": _grade_param_key(grade),
                "quantity_kg": str(qty),
            }
        )
    return rows


def _grade_separation(meta: dict) -> dict:
    block = meta.get("grade_separation")
    return dict(block) if isinstance(block, dict) else {}


def _bags_total_kg(meta: dict) -> Decimal:
    reconcile = _bag_reconciliation(meta)
    if reconcile.get("total_kg") is not None:
        return Decimal(str(reconcile["total_kg"]))
    bags_total = sum(Decimal(str(row.get("weight_kg") or 0)) for row in _bags(meta))
    if bags_total > 0:
        return bags_total
    weight_block = _weight_to_crusher(meta)
    if weight_block.get("weight_to_crusher_kg") is not None:
        return Decimal(str(weight_block["weight_to_crusher_kg"]))
    return Decimal("0")


def _scrap_total_kg(crusher: dict) -> Decimal:
    total = Decimal("0")
    for field, _, _ in MESH_GRADE_FIELDS:
        raw = crusher.get(field)
        if raw is None:
            continue
        total += Decimal(str(raw))
    return total


def _remaining_kg(meta: dict) -> Decimal:
    crusher = _crusher_output(meta)
    if crusher.get("status") != "COMPLETED":
        return Decimal("0")
    return max(Decimal("0"), _bags_total_kg(meta) - _scrap_total_kg(crusher))


def _crusher_grades_from_output(crusher: dict) -> list[dict]:
    """Legacy alias — mesh scrap rows (prefer _crusher_scrap_from_output)."""
    return _crusher_scrap_from_output(crusher)


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meta(order: CustomerOrder) -> dict:
    return dict(order.metadata_ if isinstance(order.metadata_, dict) else {})


def _json_val(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _is_raw_product(product: Product) -> bool:
    code = (product.product_code or "").upper()
    ptype = (product.product_type or "").upper()
    return ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-")


def _require_inward_order(
    db: Session, tenant: TenantContext, customer_order_id: UUID
) -> tuple[CustomerOrder, Decimal]:
    repo = _repo(db, tenant)
    order = repo.get_by_pk(
        CustomerOrder, CustomerOrder.customer_order_id, customer_order_id
    )
    meta = _meta(order)
    if meta.get("flow") != "RAW_MATERIAL_INWARD":
        raise ValidationError("Order is not a raw material inward receipt")
    lines = (
        repo.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == order.customer_order_id)
        .all()
    )
    products = {p.product_id: p for p in repo.query(Product).all()}
    qty = Decimal("0")
    for line in lines:
        product = products.get(line.product_id)
        if product and _is_raw_product(product):
            qty = Decimal(str(line.quantity or 0))
            break
    if qty <= 0 and lines:
        qty = Decimal(str(lines[0].quantity or 0))
    receipt = meta.get("inward_receipt") if isinstance(meta.get("inward_receipt"), dict) else {}
    if receipt.get("our_weight_kg") is not None:
        qty = Decimal(str(receipt["our_weight_kg"]))
    if qty <= 0:
        raise ValidationError("Inward order has no received quantity")
    return order, qty


def _initial_qc(meta: dict) -> dict:
    block = meta.get("initial_qc")
    return dict(block) if isinstance(block, dict) else {}


def _bags(meta: dict) -> list[dict]:
    rows = meta.get("inward_bags")
    return list(rows) if isinstance(rows, list) else []


def _rms_bags(meta: dict) -> list[dict]:
    return [row for row in _bags(meta) if not row.get("grade")]


def _outward_bags(meta: dict) -> list[dict]:
    return [row for row in _bags(meta) if row.get("grade")]


def _bag_reconciliation(meta: dict) -> dict:
    block = meta.get("bag_reconciliation")
    return dict(block) if isinstance(block, dict) else {}


def _inward_receipt(meta: dict) -> dict:
    block = meta.get("inward_receipt")
    return dict(block) if isinstance(block, dict) else {}


def _weight_to_crusher(meta: dict) -> dict:
    block = meta.get("weight_to_crusher")
    if isinstance(block, dict) and block.get("status"):
        return dict(block)
    legacy = _bag_reconciliation(meta)
    if legacy.get("status") == "RECONCILED":
        return {
            "status": "RECONCILED",
            "weight_to_crusher_kg": legacy.get("total_kg"),
            "received_kg": legacy.get("received_kg"),
            "variance_kg": legacy.get("variance_kg"),
            "variance_comment": legacy.get("variance_comment"),
            "reconciled_at": legacy.get("reconciled_at"),
            "source": "legacy_bag_reconciliation",
        }
    return {}


def _is_bags_reconciled(meta: dict) -> bool:
    if _bag_reconciliation(meta).get("status") == "RECONCILED":
        return True
    return _weight_to_crusher(meta).get("status") == "RECONCILED"


def _is_weight_reconciled(meta: dict) -> bool:
    return _is_bags_reconciled(meta)


def _crusher_output(meta: dict) -> dict:
    block = meta.get("crusher_output")
    return dict(block) if isinstance(block, dict) else {}


def workflow_status_from_meta(meta: dict, received_kg: Decimal) -> dict:
    initial = _initial_qc(meta)
    initial_status = (initial.get("qc_status") or "PENDING").upper()
    receipt = _inward_receipt(meta)
    supplier_weight_kg = (
        Decimal(str(receipt["supplier_weight_kg"]))
        if receipt.get("supplier_weight_kg") is not None
        else None
    )
    weight_block = _weight_to_crusher(meta)
    reconcile = _bag_reconciliation(meta)
    bags_reconciled = _is_bags_reconciled(meta)
    weight_to_crusher_kg = (
        Decimal(str(reconcile["total_kg"]))
        if reconcile.get("total_kg") is not None
        else (
            Decimal(str(weight_block["weight_to_crusher_kg"]))
            if weight_block.get("weight_to_crusher_kg") is not None
            else None
        )
    )
    variance_comment = reconcile.get("variance_comment") or weight_block.get("variance_comment")
    legacy_bags = _bags(meta)
    bags_total = sum(Decimal(str(row.get("weight_kg") or 0)) for row in legacy_bags)
    crusher = _crusher_output(meta)
    crusher_complete = crusher.get("status") == "COMPLETED"
    scrap_total_kg = _scrap_total_kg(crusher) if crusher_complete else Decimal("0")
    remaining_kg = _remaining_kg(meta) if crusher_complete else None
    separation = _grade_separation(meta)
    separation_complete = separation.get("status") == "COMPLETED"
    separation_grades = (
        _separation_grades_from_block(separation) if separation_complete else []
    )
    crusher_scrap = _crusher_scrap_from_output(crusher) if crusher_complete else []
    return {
        "initial_qc_status": initial_status,
        "initial_qc_at": initial.get("qc_at"),
        "moisture_pct": initial.get("moisture_pct"),
        "dust_pct": initial.get("dust_pct"),
        "ad_value": initial.get("ad_value"),
        "received_kg": received_kg,
        "supplier_weight_kg": supplier_weight_kg,
        "weight_to_crusher_kg": weight_to_crusher_kg or (bags_total if bags_total else None),
        "weight_reconciled": bags_reconciled,
        "variance_comment": variance_comment,
        "bag_count": len(legacy_bags),
        "bags_total_kg": bags_total if legacy_bags else weight_to_crusher_kg,
        "bags_reconciled": bags_reconciled,
        "bag_variance_comment": variance_comment,
        "crusher_complete": crusher_complete,
        "crusher_at": crusher.get("completed_at"),
        "rotary": crusher.get("rotary"),
        "scrap_total_kg": scrap_total_kg if crusher_complete else None,
        "remaining_kg": remaining_kg,
        "separation_complete": separation_complete,
        "crusher_grades": separation_grades,
        "crusher_scrap": crusher_scrap,
    }


def build_workflow_out(
    db: Session, tenant: TenantContext, order: CustomerOrder
) -> Optional[AcInboundWorkflowOut]:
    repo = _repo(db, tenant)
    lines = (
        repo.query(CustomerOrderLine)
        .filter(CustomerOrderLine.order_id == order.customer_order_id)
        .all()
    )
    products = {p.product_id: p for p in repo.query(Product).all()}
    raw_line = None
    for line in lines:
        product = products.get(line.product_id)
        if product and _is_raw_product(product):
            raw_line = (line, product)
            break
    if not raw_line and not lines:
        return None
    line, product = raw_line if raw_line else (lines[0], products.get(lines[0].product_id))
    received_kg = Decimal(str(line.quantity or 0))
    meta = _meta(order)
    status = workflow_status_from_meta(meta, received_kg)
    grades = status.pop("crusher_grades", [])
    scrap = status.pop("crusher_scrap", [])
    from app.schemas.mes_core.schemas import AcCrusherGradeOut

    return AcInboundWorkflowOut(
        customer_order_id=order.customer_order_id,
        order_code=order.order_code,
        product_code=product.product_code if product else None,
        product_name=product.product_name if product else None,
        quantity=received_kg,
        uom=line.uom,
        crusher_grades=[
            AcCrusherGradeOut(
                grade_label=row["grade_label"],
                parameter_key=row["parameter_key"],
                quantity_kg=Decimal(str(row["quantity_kg"])),
            )
            for row in grades
        ],
        crusher_scrap=[
            AcCrusherGradeOut(
                grade_label=row["grade_label"],
                parameter_key=row["parameter_key"],
                quantity_kg=Decimal(str(row["quantity_kg"])),
            )
            for row in scrap
        ],
        **status,
    )


def list_inbound_workflow(
    db: Session, tenant: TenantContext
) -> list[AcInboundWorkflowOut]:
    repo = _repo(db, tenant)
    orders = repo.query(CustomerOrder).order_by(CustomerOrder.created_at.desc()).all()
    rows: list[AcInboundWorkflowOut] = []
    for order in orders:
        row = build_workflow_out(db, tenant, order)
        if row:
            rows.append(row)
    return rows


def _stage_initial_qc_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    payload: dict,
) -> None:
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:tested_by",
            object_uri=f"urn:nyra:ac:initialQc:{order.order_code}",
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    for field, param_uri, datatype in (
        ("moisture_pct", "urn:nyra:ac:parameter:MOISTURE_PCT", "decimal"),
        ("dust_pct", "urn:nyra:ac:parameter:DUST_PCT", "decimal"),
        ("ad_value", "urn:nyra:ac:parameter:AD_VALUE", "decimal"),
        ("qc_status", "urn:nyra:ac:parameter:QC_DECISION", "string"),
    ):
        value = payload.get(field)
        if value is None:
            continue
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=param_uri,
                object_literal=str(value),
                object_datatype=(
                    "http://www.w3.org/2001/XMLSchema#decimal"
                    if datatype == "decimal"
                    else "http://www.w3.org/2001/XMLSchema#string"
                ),
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )


def create_initial_qc(
    db: Session, tenant: TenantContext, payload: AcInitialQcCreate
) -> AcInitialQcOut:
    order, _ = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    if _initial_qc(meta):
        raise ValidationError(
            f"Order '{order.order_code}' already has an initial QC record."
        )
    qc_status = (payload.qc_status or "PASS").upper()
    if qc_status not in ("PASS", "HOLD", "FAIL", "QC_PASSED", "QC_FAILED", "APPROVED", "REJECTED"):
        raise ValidationError("Select whether to proceed with this inward.")
    qc_payload = {
        "moisture_pct": _json_val(payload.moisture_pct),
        "dust_pct": _json_val(payload.dust_pct),
        "ad_value": _json_val(payload.ad_value),
        "qc_status": qc_status,
        "qc_at": _utcnow_iso(),
    }
    meta["initial_qc"] = qc_payload
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    _stage_initial_qc_triples(db, tenant, order, qc_payload)
    repo.db.commit()
    repo.db.refresh(order)
    row = build_workflow_out(db, tenant, order)
    assert row is not None
    return AcInitialQcOut.model_validate(row.model_dump())


def _next_bag_code(bags: list[dict]) -> str:
    nums = []
    for row in bags:
        match = str(row.get("bag_code") or "")
        if match.startswith("BAG-AC-"):
            try:
                nums.append(int(match.split("-")[-1]))
            except ValueError:
                pass
    next_num = (max(nums) if nums else 1000) + 1
    return f"BAG-AC-{next_num}"


def _stage_inward_bag_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    bag: dict,
) -> None:
    subject = f"urn:nyra:ac:inwardBag:{bag['bag_code']}"
    inward_uri = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:containedIn",
            object_uri=inward_uri,
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    if bag.get("grade"):
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri="urn:nyra:ac:parameter:BAG_GRADE",
                object_literal=str(bag["grade"]),
                object_datatype="http://www.w3.org/2001/XMLSchema#string",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )
    if bag.get("weight_kg") is not None:
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri="urn:nyra:ac:parameter:BAG_WEIGHT_KG",
                object_literal=str(bag["weight_kg"]),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )


def _lab_execution_decision(meta: dict) -> str:
    exec_map = meta.get("inbound_execution")
    if not isinstance(exec_map, dict):
        return ""
    lab = exec_map.get("IN-LAB")
    if not isinstance(lab, dict):
        return ""
    return str(lab.get("qc_decision") or lab.get("qc_status") or "").strip().upper()


def lab_approved(meta: dict) -> bool:
    initial = _initial_qc(meta)
    status = (initial.get("qc_status") or "").upper()
    if status in ("PASS", "QC_PASSED", "APPROVED"):
        return True
    decision = _lab_execution_decision(meta)
    return decision in ("APPROVE", "APPROVED", "PASS", "QC_PASSED")


def _assert_initial_qc_ready(meta: dict, order_code: str) -> None:
    initial = _initial_qc(meta)
    status = (initial.get("qc_status") or "").upper()
    decision = _lab_execution_decision(meta)
    if status in ("FAIL", "QC_FAILED", "REJECTED") or decision in ("DENY", "FAIL", "REJECTED"):
        raise ValidationError(
            f"Order '{order_code}' was not approved — cannot split into bags."
        )
    if status in ("HOLD",) or decision == "HOLD":
        raise ValidationError(
            f"Order '{order_code}' is on hold — approve before splitting into bags."
        )
    if lab_approved(meta):
        return
    raise ValidationError(
        f"Order '{order_code}' requires Lab approve before RMS inward bags."
    )


def _stage_weight_to_crusher_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    payload: dict,
) -> None:
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=subject,
            predicate_uri="urn:nyra:predicate:captures",
            object_uri="urn:nyra:ac:parameter:WEIGHT_TO_CRUSHER_KG",
            object_literal=str(payload.get("weight_to_crusher_kg")),
            object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
            source_table="trn.customer_order",
            source_id=source_id,
        ),
    )
    if payload.get("variance_comment"):
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri="urn:nyra:ac:parameter:WEIGHT_VARIANCE_COMMENT",
                object_literal=str(payload["variance_comment"]),
                object_datatype="http://www.w3.org/2001/XMLSchema#string",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )


def record_weight_to_crusher(
    db: Session, tenant: TenantContext, payload: AcWeightToCrusherCreate
) -> AcInboundWorkflowOut:
    order, received_kg = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    _assert_initial_qc_ready(meta, order.order_code)
    if _is_weight_reconciled(meta):
        raise ValidationError(
            f"Order '{order.order_code}' weight is already reconciled for crusher."
        )
    weight_kg = Decimal(str(payload.weight_to_crusher_kg))
    if weight_kg <= 0:
        raise ValidationError("Weight to crusher must be greater than zero.")
    variance_kg = received_kg - weight_kg
    comment = (payload.variance_comment or "").strip()
    if abs(variance_kg) > Decimal("0.01") and not comment:
        raise ValidationError(
            f"Weight to crusher {weight_kg} KG differs from received {received_kg} KG — "
            "add a variance comment."
        )
    weight_payload = {
        "status": "RECONCILED",
        "weight_to_crusher_kg": str(weight_kg),
        "received_kg": str(received_kg),
        "variance_kg": str(variance_kg),
        "variance_comment": comment or None,
        "reconciled_at": _utcnow_iso(),
    }
    meta["weight_to_crusher"] = weight_payload
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    _stage_weight_to_crusher_triples(db, tenant, order, weight_payload)
    repo.db.commit()
    row = build_workflow_out(db, tenant, order)
    assert row is not None
    return row


def list_inward_bags(
    db: Session,
    tenant: TenantContext,
    *,
    order_code: Optional[str] = None,
    customer_order_id: Optional[UUID] = None,
) -> list[AcInwardBagOut]:
    repo = _repo(db, tenant)
    orders = repo.query(CustomerOrder).order_by(CustomerOrder.created_at.desc()).all()
    rows: list[AcInwardBagOut] = []
    for order in orders:
        meta = _meta(order)
        if meta.get("flow") != "RAW_MATERIAL_INWARD":
            continue
        if order_code and order.order_code != order_code:
            continue
        if customer_order_id and order.customer_order_id != customer_order_id:
            continue
        for bag in _bags(meta):
            rows.append(
                AcInwardBagOut(
                    bag_id=UUID(str(bag["bag_id"])),
                    bag_code=str(bag["bag_code"]),
                    customer_order_id=order.customer_order_id,
                    order_code=order.order_code,
                    grade=bag.get("grade"),
                    weight_kg=Decimal(str(bag.get("weight_kg") or 0)),
                    label=bag.get("label"),
                    status=bag.get("status") or "REGISTERED",
                    created_at=bag.get("created_at"),
                    fed_at=bag.get("fed_at"),
                )
            )
    return rows


def create_inward_bag(
    db: Session, tenant: TenantContext, payload: AcInwardBagCreate
) -> AcInwardBagOut:
    order, received_kg = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    _assert_initial_qc_ready(meta, order.order_code)
    allowed_grades = ac_inbound_admin.outward_split_labels(db, tenant)
    grade = (payload.grade or "").strip() or None
    if _bag_reconciliation(meta).get("status") == "RECONCILED" and not grade:
        raise ValidationError(
            f"Order '{order.order_code}' RMS bags are reconciled — add RM outward bags with a split grade."
        )
    if grade and grade not in allowed_grades and grade not in BAG_GRADES:
        raise ValidationError(
            f"Invalid bag grade — choose one of: {', '.join(allowed_grades)}"
        )
    bags = _bags(meta)
    weight_kg = Decimal(str(payload.weight_kg))
    if weight_kg <= 0:
        raise ValidationError("Bag quantity must be greater than zero.")
    if not grade:
        rms_total = sum(Decimal(str(row.get("weight_kg") or 0)) for row in _rms_bags(meta))
        if rms_total + weight_kg > received_kg + Decimal("0.001"):
            remaining = received_kg - rms_total
            raise ValidationError(
                f"Bag quantity exceeds inward weight — only {remaining} KG remaining of {received_kg} KG."
            )
    bag_code = _next_bag_code(bags)
    bag_row = {
        "bag_id": str(uuid4()),
        "bag_code": bag_code,
        "grade": grade,
        "weight_kg": str(payload.weight_kg),
        "label": payload.label,
        "status": "REGISTERED",
        "created_at": _utcnow_iso(),
    }
    bags.append(bag_row)
    meta["inward_bags"] = bags
    if not grade and _bag_reconciliation(meta):
        meta.pop("bag_reconciliation", None)
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    _stage_inward_bag_triples(db, tenant, order, bag_row)
    repo.db.commit()
    return AcInwardBagOut(
        bag_id=UUID(bag_row["bag_id"]),
        bag_code=bag_row["bag_code"],
        customer_order_id=order.customer_order_id,
        order_code=order.order_code,
        grade=grade,
        weight_kg=payload.weight_kg,
        label=payload.label,
        status="REGISTERED",
        created_at=bag_row["created_at"],
    )


def feed_inward_bag_to_crusher(
    db: Session, tenant: TenantContext, payload
) -> AcInwardBagOut:
    order, _ = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    _assert_initial_qc_ready(meta, order.order_code)
    if not _is_bags_reconciled(meta):
        raise ValidationError(
            f"Order '{order.order_code}' — complete RMS inward (bag total = inward weight) before crusher feed."
        )
    bags = _bags(meta)
    bag_key = str(payload.bag_id)
    found = None
    for row in bags:
        if str(row.get("bag_id")) == bag_key:
            found = row
            break
    if found is None:
        raise ValidationError("Bag not found on this inward order.")
    if found.get("grade"):
        raise ValidationError("Only RMS inward bags are fed to the crusher.")
    if (found.get("status") or "").upper() == "FED_TO_CRUSHER":
        raise ValidationError(f"Bag {found.get('bag_code')} is already fed to the crusher.")
    nxt = next_rms_bag_to_feed(meta)
    if nxt and str(nxt.get("bag_id")) != bag_key:
        raise ValidationError(
            f"Feed RMS bags one by one — next bag is {nxt.get('bag_code')}."
        )
    found["status"] = "FED_TO_CRUSHER"
    found["fed_at"] = _utcnow_iso()
    meta["inward_bags"] = bags
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    mes_core_entities.create_triple(
        db,
        tenant,
        TripleCreate(
            subject_uri=f"urn:nyra:ac:inwardBag:{found['bag_code']}",
            predicate_uri="urn:nyra:predicate:captures",
            object_uri="urn:nyra:ac:parameter:FED_TO_CRUSHER",
            object_literal="true",
            object_datatype="http://www.w3.org/2001/XMLSchema#boolean",
            source_table="trn.customer_order",
            source_id=order.customer_order_id,
        ),
    )
    repo.db.commit()
    return AcInwardBagOut(
        bag_id=UUID(str(found["bag_id"])),
        bag_code=str(found["bag_code"]),
        customer_order_id=order.customer_order_id,
        order_code=order.order_code,
        grade=found.get("grade"),
        weight_kg=Decimal(str(found.get("weight_kg") or 0)),
        label=found.get("label"),
        status=found.get("status") or "FED_TO_CRUSHER",
        created_at=found.get("created_at"),
        fed_at=found.get("fed_at"),
    )


def next_rms_bag_to_feed(meta: dict) -> dict | None:
    for row in _rms_bags(meta):
        if (row.get("status") or "").upper() != "FED_TO_CRUSHER":
            return row
    return None


def all_bags_fed_to_crusher(meta: dict) -> bool:
    bags = _rms_bags(meta)
    if not bags:
        return False
    return all((row.get("status") or "").upper() == "FED_TO_CRUSHER" for row in bags)


def reconcile_inward_bags(
    db: Session, tenant: TenantContext, payload: AcInwardBagReconcileCreate
) -> AcInboundWorkflowOut:
    order, received_kg = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    _assert_initial_qc_ready(meta, order.order_code)
    bags = _rms_bags(meta)
    if not bags:
        raise ValidationError(
            f"Order '{order.order_code}' has no registered bags to reconcile."
        )
    total_kg = sum(Decimal(str(row.get("weight_kg") or 0)) for row in bags)
    if total_kg > received_kg + Decimal("0.001"):
        raise ValidationError(
            f"Bags total {total_kg} KG exceeds received {received_kg} KG — remove or reduce bags."
        )
    variance_kg = received_kg - total_kg
    comment = (payload.variance_comment or "").strip()
    if variance_kg > Decimal("0.01") and not comment:
        raise ValidationError(
            f"RMS bag total {total_kg} KG is less than inward weight {received_kg} KG "
            f"(short by {variance_kg} KG) — enter remarks."
        )
    meta["bag_reconciliation"] = {
        "status": "RECONCILED",
        "total_kg": str(total_kg),
        "received_kg": str(received_kg),
        "variance_kg": str(variance_kg),
        "variance_comment": comment or None,
        "reconciled_at": _utcnow_iso(),
    }
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    repo.db.commit()
    row = build_workflow_out(db, tenant, order)
    assert row is not None
    return row


def delete_inward_bag(
    db: Session,
    tenant: TenantContext,
    *,
    customer_order_id: UUID,
    bag_id: UUID,
) -> AcInboundWorkflowOut:
    order, _ = _require_inward_order(db, tenant, customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    bags = _bags(meta)
    bag_key = str(bag_id)
    found = next((row for row in bags if str(row.get("bag_id")) == bag_key), None)
    if found is None:
        raise ValidationError("Bag not found on this inward order.")
    reconciled = _bag_reconciliation(meta).get("status") == "RECONCILED"
    if reconciled and not found.get("grade"):
        raise ValidationError(
            f"Order '{order.order_code}' RMS bags are reconciled — cannot remove them."
        )
    kept = [row for row in bags if str(row.get("bag_id")) != bag_key]
    meta["inward_bags"] = kept
    if not found.get("grade") and _bag_reconciliation(meta):
        meta.pop("bag_reconciliation", None)
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    repo.db.commit()
    row = build_workflow_out(db, tenant, order)
    assert row is not None
    return row


def _stage_crusher_output_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    payload: dict,
) -> None:
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    object_uri = f"urn:nyra:ac:crusherOutput:{order.order_code}"
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
    for field, _, param_code in (*MESH_GRADE_FIELDS, *MESH_PCT_FIELDS):
        value = payload.get(field)
        if value is None or value == "":
            continue
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=f"urn:nyra:ac:parameter:{param_code}",
                object_literal=str(value),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )
    for field, param_code in (
        ("rotary", "CRUSHER_ROTARY"),
        ("crusher_grade", "CRUSHER_GRADE"),
        ("moisture_pct", "MOISTURE_PCT"),
        ("dust_pct", "DUST_PCT"),
    ):
        value = payload.get(field)
        if value is None:
            continue
        datatype = (
            "http://www.w3.org/2001/XMLSchema#string"
            if field in ("rotary", "crusher_grade")
            else "http://www.w3.org/2001/XMLSchema#decimal"
        )
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=f"urn:nyra:ac:parameter:{param_code}",
                object_literal=str(value),
                object_datatype=datatype,
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )


def create_crusher_output(
    db: Session, tenant: TenantContext, payload: AcCrusherOutputCreate
) -> AcCrusherOutputOut:
    order, received_kg = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    if not _is_bags_reconciled(meta):
        raise ValidationError(
            f"Order '{order.order_code}' — split into bags and reconcile totals before crusher entry."
        )
    if _crusher_output(meta).get("status") == "COMPLETED":
        raise ValidationError(
            f"Order '{order.order_code}' already has crusher output recorded."
        )
    rotary = (payload.rotary or "").strip()
    allowed_rotaries = ac_inbound_admin.rotary_names(db, tenant)
    if rotary not in allowed_rotaries and rotary not in ROTARY_OPTIONS:
        raise ValidationError(f"Select rotary: {', '.join(allowed_rotaries)}")
    if not all_bags_fed_to_crusher(meta):
        raise ValidationError(
            f"Order '{order.order_code}' — feed every RMS bag to the crusher before recording performance."
        )

    mesh_values = {
        field: _json_val(getattr(payload, field, None))
        for field, _, _ in (*MESH_GRADE_FIELDS, *MESH_PCT_FIELDS)
        if getattr(payload, field, None) is not None
    }
    crusher_grade = (getattr(payload, "crusher_grade", None) or "").strip() or None
    if payload.moisture_pct is None or payload.dust_pct is None:
        raise ValidationError("Enter dust (%) and moisture (%).")

    crusher_payload = {
        "rotary": rotary,
        **mesh_values,
        "moisture_pct": _json_val(payload.moisture_pct),
        "dust_pct": _json_val(payload.dust_pct),
        "status": "COMPLETED",
        "completed_at": _utcnow_iso(),
    }
    if crusher_grade:
        crusher_payload["crusher_grade"] = crusher_grade
    meta["crusher_output"] = crusher_payload

    initial = _initial_qc(meta)
    initial_status = (initial.get("qc_status") or "PASS").upper()
    if initial_status in ("PASS", "QC_PASSED", "APPROVED"):
        meta.setdefault("raw_material_qc", {})
        if isinstance(meta["raw_material_qc"], dict):
            meta["raw_material_qc"] = {
                **meta["raw_material_qc"],
                "moisture_pct": initial.get("moisture_pct"),
                "qc_status": "QC_PASSED",
                "qc_at": _utcnow_iso(),
                "source": "initial_qc_after_crusher",
            }
        order.status = "QC_PASSED"

    order.metadata_ = meta
    flag_modified(order, "metadata_")
    _stage_crusher_output_triples(db, tenant, order, crusher_payload)
    repo.db.commit()
    repo.db.refresh(order)
    row = build_workflow_out(db, tenant, order)
    assert row is not None
    return AcCrusherOutputOut.model_validate(row.model_dump())


def _stage_inward_grade_separation_triples(
    db: Session,
    tenant: TenantContext,
    order: CustomerOrder,
    payload: dict,
) -> None:
    subject = f"urn:nyra:ac:inward:{order.order_code}"
    source_id = order.customer_order_id
    object_uri = f"urn:nyra:ac:gradeSeparation:{order.order_code}"
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
    for entry in payload.get("grade_splits") or []:
        grade = (entry.get("grade_label") or "").strip()
        qty = entry.get("quantity_kg")
        if not grade or qty is None:
            continue
        mes_core_entities.create_triple(
            db,
            tenant,
            TripleCreate(
                subject_uri=subject,
                predicate_uri="urn:nyra:predicate:captures",
                object_uri=f"urn:nyra:ac:parameter:{_grade_param_key(grade).upper()}",
                object_literal=str(qty),
                object_datatype="http://www.w3.org/2001/XMLSchema#decimal",
                source_table="trn.customer_order",
                source_id=source_id,
            ),
        )


def create_inward_grade_separation(
    db: Session, tenant: TenantContext, payload: AcInwardGradeSeparationCreate
) -> AcInboundWorkflowOut:
    order, _ = _require_inward_order(db, tenant, payload.customer_order_id)
    repo = _repo(db, tenant)
    meta = _meta(order)
    if _crusher_output(meta).get("status") != "COMPLETED":
        raise ValidationError(
            f"Order '{order.order_code}' — record crusher scrap before grade separation."
        )
    if _grade_separation(meta).get("status") == "COMPLETED":
        raise ValidationError(
            f"Order '{order.order_code}' grade separation is already complete."
        )
    if not payload.grade_splits:
        raise ValidationError("Add at least one grade split.")

    remaining = _remaining_kg(meta)
    splits: list[dict] = []
    total = Decimal("0")
    for row in payload.grade_splits:
        grade = (row.grade_label or "").strip()
        allowed = ac_inbound_admin.outward_split_labels(db, tenant)
        if grade not in allowed and grade not in BAG_GRADES:
            raise ValidationError(f"Invalid outward split — choose one of: {', '.join(allowed)}")
        qty = Decimal(str(row.quantity_kg))
        if qty <= 0:
            raise ValidationError("Grade quantity must be greater than zero.")
        total += qty
        splits.append({"grade_label": grade, "quantity_kg": str(qty)})

    if total > remaining + Decimal("0.001"):
        raise ValidationError(
            f"Grade total {total} KG exceeds remaining {remaining} KG after scrap."
        )

    separation_payload = {
        "status": "COMPLETED",
        "grade_splits": splits,
        "remaining_kg": str(remaining),
        "allocated_kg": str(total),
        "completed_at": _utcnow_iso(),
    }
    meta["grade_separation"] = separation_payload
    order.metadata_ = meta
    flag_modified(order, "metadata_")
    _stage_inward_grade_separation_triples(db, tenant, order, separation_payload)
    repo.db.commit()
    row = build_workflow_out(db, tenant, order)
    assert row is not None
    return row
