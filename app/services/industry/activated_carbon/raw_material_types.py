"""Activated Carbon raw material type master — product + routing bundle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.execution import OperationExecution
from app.models.mes_core.master import Product, Routing, RoutingOperation
from app.schemas.mes_core.schemas import (
    AcRawMaterialProcessParameter,
    AcRawMaterialTypeCreate,
    AcRawMaterialTypeOperation,
    AcRawMaterialTypeOut,
    AcRawMaterialTypeUpdate,
    AcRawMaterialTypeUsageOut,
    ProductCreate,
    RoutingOperationCreate,
    RoutingWithOperationsCreate,
)
from app.services.industry.activated_carbon import process_rules as ac_process_rules
from app.services.industry.activated_carbon.raw_material_usage import raw_material_usage
from app.services.industry.activated_carbon.codes import (
    resolve_ac_business_code,
    sync_ac_sequences,
)
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _product_meta(product: Product) -> dict:
    raw = product.metadata_
    return dict(raw) if isinstance(raw, dict) else {}


def _set_product_metadata(product: Product, meta: dict) -> None:
    product.metadata_ = dict(meta)
    flag_modified(product, "metadata_")


def _set_operation_metadata(row: RoutingOperation, meta: dict) -> None:
    row.metadata_ = dict(meta)
    flag_modified(row, "metadata_")


def _uuid_or_none(value) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _operation_process_step(row: RoutingOperation) -> str:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return (
        meta.get("process_step")
        or meta.get("process_code")
        or meta.get("process_type")
        or ""
    )


def _operation_dict(row: RoutingOperation) -> dict:
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return {
        "operation_sequence": row.operation_sequence,
        "operation_name": row.operation_name,
        "operation_code": row.operation_code,
        "process_step": _operation_process_step(row) or row.operation_code.replace("OP-", "", 1),
        "is_mandatory": meta.get("is_mandatory", True),
    }


def _operations_from_routing(
    db: Session, tenant: TenantContext, routing_id: UUID
) -> list[dict]:
    rows = (
        _repo(db, tenant)
        .query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing_id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    return [_operation_dict(row) for row in rows]


def _operation_codes(operations) -> set[str]:
    codes: set[str] = set()
    for op in operations or []:
        if isinstance(op, dict):
            code = (op.get("operation_code") or "").strip().upper()
        else:
            code = (getattr(op, "operation_code", None) or "").strip().upper()
        if code:
            codes.add(code)
    return codes


def _apply_process_metadata(meta: dict, process_step: str, is_mandatory: bool = True) -> dict:
    step = (process_step or "").strip()
    return {
        **meta,
        "process_step": step,
        "process_code": step,
        "process_type": step,
        "is_mandatory": is_mandatory,
    }


def _set_row_sequence(row: RoutingOperation, sequence: int) -> None:
    row.operation_sequence = sequence
    if hasattr(row, "operation_seq"):
        row.operation_seq = sequence


def rebase_operation_sequences(rows) -> None:
    """Park sequences above 1..n so a later assign can swap freely."""
    for index, row in enumerate(rows):
        _set_row_sequence(row, 10_000 + index)


def assign_operation_sequences(rows_by_code: dict[str, RoutingOperation], desired: dict[str, int]) -> None:
    for code, sequence in desired.items():
        row = rows_by_code.get(code)
        if row is not None:
            _set_row_sequence(row, sequence)


def _sync_routing_operations(
    db: Session,
    tenant: TenantContext,
    routing_id: UUID,
    operations: list[AcRawMaterialTypeOperation],
) -> None:
    """Align mst.routing_operation rows with the raw-material process definition."""
    if not operations:
        raise ValidationError("At least one routing operation is required.")

    repo = _repo(db, tenant)
    sequences = [op.operation_sequence for op in operations]
    if len(sequences) != len(set(sequences)):
        raise ValidationError("Duplicate operation sequence values in routing.")

    existing = (
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing_id)
        .all()
    )
    by_code = {row.operation_code: row for row in existing}
    keep_codes: set[str] = set()
    desired_sequences: dict[str, int] = {}

    for op_in in sorted(operations, key=lambda o: o.operation_sequence):
        code = (op_in.operation_code or "").strip()
        if not code:
            code = resolve_ac_business_code(
                db, provided=None, entity="routing_operation"
            )
        keep_codes.add(code)
        desired_sequences[code] = op_in.operation_sequence
        step = (op_in.process_step or "").strip()
        mandatory = getattr(op_in, "is_mandatory", True)
        if code in by_code:
            row = by_code[code]
            row.operation_name = op_in.operation_name.strip()
            _set_operation_metadata(
                row,
                _apply_process_metadata(
                    row.metadata_ if isinstance(row.metadata_, dict) else {},
                    step,
                    mandatory,
                ),
            )
            continue

        op_code = resolve_ac_business_code(db, provided=code, entity="routing_operation")
        row = repo.add(
            RoutingOperation(
                routing_id=routing_id,
                operation_code=op_code,
                operation_sequence=op_in.operation_sequence + 10_000,
                operation_name=op_in.operation_name.strip(),
                metadata_=_apply_process_metadata({}, step, mandatory),
            )
        )
        if hasattr(row, "operation_seq"):
            row.operation_seq = op_in.operation_sequence + 10_000
        by_code[op_code] = row
        if op_code != code:
            desired_sequences[op_code] = desired_sequences.pop(code)
            keep_codes.discard(code)
            keep_codes.add(op_code)

    rebase_operation_sequences(by_code.values())
    repo.db.flush()
    assign_operation_sequences(by_code, desired_sequences)
    repo.db.flush()

    for row in existing:
        if row.operation_code not in keep_codes:
            exec_count = (
                repo.query(OperationExecution)
                .filter(OperationExecution.routing_operation_id == row.routing_operation_id)
                .count()
            )
            if exec_count:
                step = _operation_process_step(row)
                raise ValidationError(
                    "Cannot remove or replace process step "
                    f"'{row.operation_name}' ({step or row.operation_code}) — "
                    f"{exec_count} shop-floor execution(s) already reference it. "
                    "Mark the raw material obsolete instead of changing steps that "
                    "have production history."
                )
            repo.db.delete(row)

    repo.db.flush()


def _bootstrap_routing_for_legacy_type(
    db: Session,
    tenant: TenantContext,
    raw: Product,
    meta: dict,
    operations: list[AcRawMaterialTypeOperation],
    *,
    finished_product_name: Optional[str] = None,
) -> tuple[UUID, str, Product]:
    """Create FG product + routing for legacy raw materials missing a linked route."""
    if not operations:
        raise ValidationError("At least one routing operation is required.")

    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)

    finished_id = _uuid_or_none(meta.get("finished_product_id"))
    fg_code = (meta.get("finished_product_code") or "").strip()
    fg_name = (finished_product_name or meta.get("finished_product_name") or raw.product_name).strip()
    if not fg_name:
        raise ValidationError("Finished product name is required")

    finished: Optional[Product] = None
    if finished_id:
        try:
            finished = repo.get_by_pk(Product, Product.product_id, finished_id)
        except NotFoundError:
            finished = None
    if finished is None and fg_code:
        try:
            finished = repo.get_by_code(Product, Product.product_code, fg_code)
        except NotFoundError:
            finished = None
    if finished is None:
        fg_code = resolve_ac_business_code(
            db, provided=fg_code or None, entity="ac_finished_product", tenant_id=tenant.tenant_id
        )
        finished_out = mes_core_entities.create_product(
            db,
            tenant,
            ProductCreate(
                product_code=fg_code,
                product_name=fg_name,
                product_type="FINISHED_GOOD",
                uom="KG",
            ),
        )
        finished = repo.get_by_pk(Product, Product.product_id, finished_out.product_id)

    routing_code = resolve_ac_business_code(
        db,
        provided=meta.get("routing_code") or None,
        entity="ac_routing",
        tenant_id=tenant.tenant_id,
    )
    routing_out = mes_core_entities.create_routing_with_operations(
        db,
        tenant,
        RoutingWithOperationsCreate(
            routing_code=routing_code,
            product_id=finished.product_id,
            routing_version="1",
            process_family="ACTIVATED_CARBON",
            operations=[
                RoutingOperationCreate(
                    operation_code=op.operation_code,
                    operation_sequence=op.operation_sequence,
                    operation_name=op.operation_name,
                    process_code=op.process_step,
                    process_type=op.process_step,
                )
                for op in operations
            ],
        ),
    )
    routing_id = routing_out.routing.routing_id
    _sync_routing_operations(db, tenant, routing_id, operations)
    return routing_id, routing_out.routing.routing_code, finished


def _product_is_obsolete(product: Product) -> bool:
    status = (product.status or "").upper()
    if status == "OBSOLETE":
        return True
    meta = product.metadata_ if isinstance(product.metadata_, dict) else {}
    return bool(meta.get("obsolete") or meta.get("is_obsolete"))


def _type_from_product(
    db: Session,
    tenant: TenantContext,
    product: Product,
    *,
    include_usage: bool = True,
) -> Optional[AcRawMaterialTypeOut]:
    meta = _product_meta(product)
    if not meta.get("ac_raw_material_type"):
        return None

    routing_id = _uuid_or_none(meta.get("routing_id"))
    if routing_id:
        operations = _operations_from_routing(db, tenant, routing_id)
    else:
        operations = meta.get("operations") or []
    operations = ac_process_rules.without_kiln_feed_bag_qc_operations(operations)

    usage_out = None
    if include_usage:
        usage = raw_material_usage(db, tenant, product.product_id)
        usage_out = AcRawMaterialTypeUsageOut(**usage)

    is_obsolete = _product_is_obsolete(product)
    status = "OBSOLETE" if is_obsolete else (product.status or "ACTIVE")

    return AcRawMaterialTypeOut(
        product_id=product.product_id,
        product_code=product.product_code,
        product_name=product.product_name,
        finished_product_code=meta.get("finished_product_code"),
        finished_product_name=meta.get("finished_product_name"),
        finished_product_id=_uuid_or_none(meta.get("finished_product_id")),
        routing_code=meta.get("routing_code"),
        routing_id=routing_id,
        operations=operations,
        inbound_operations=ac_process_rules.normalized_inbound_operations(
            meta.get("inbound_operations") or []
        ),
        process_parameters=ac_process_rules.without_kiln_feed_bag_qc_parameters(
            meta.get("process_parameters") or []
        ),
        status=status,
        is_obsolete=is_obsolete,
        usage=usage_out,
    )


def _legacy_type_out(
    db: Session, tenant: TenantContext, row: Product, *, include_usage: bool = True
) -> AcRawMaterialTypeOut:
    usage_out = None
    if include_usage:
        usage = raw_material_usage(db, tenant, row.product_id)
        usage_out = AcRawMaterialTypeUsageOut(**usage)
    is_obsolete = _product_is_obsolete(row)
    return AcRawMaterialTypeOut(
        product_id=row.product_id,
        product_code=row.product_code,
        product_name=row.product_name,
        finished_product_code=None,
        operations=[],
        inbound_operations=ac_process_rules.normalized_inbound_operations([]),
        process_parameters=[],
        status="OBSOLETE" if is_obsolete else (row.status or "ACTIVE"),
        is_obsolete=is_obsolete,
        usage=usage_out,
    )


def _is_gr_coconut_shell(typed: AcRawMaterialTypeOut) -> bool:
    code = (typed.product_code or "").upper()
    name = (typed.product_name or "").lower()
    if code == "RAW-COCO-SHELL":
        return True
    return "coconut" in name and ("(gr)" in name or name.endswith(" gr") or " gr " in name)


def list_raw_material_types(
    db: Session,
    tenant: TenantContext,
    *,
    active_only: bool = False,
    include_usage: bool = True,
    restrict_plant_material: bool = True,
) -> List[AcRawMaterialTypeOut]:
    rows = _repo(db, tenant).query(Product).order_by(Product.product_code).all()
    out: list[AcRawMaterialTypeOut] = []
    for row in rows:
        typed = _type_from_product(db, tenant, row, include_usage=include_usage)
        if typed:
            if active_only and typed.is_obsolete:
                continue
            out.append(typed)
            continue
        ptype = (row.product_type or "").upper()
        code = (row.product_code or "").upper()
        if ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-"):
            legacy = _legacy_type_out(db, tenant, row, include_usage=include_usage)
            if active_only and legacy.is_obsolete:
                continue
            out.append(legacy)
    tenant_code = (getattr(tenant, "tenant_code", None) or "").upper()
    if restrict_plant_material and tenant_code in {
        "GR_CARBONS",
        "SAM_CARBONS",
        "SAM_CARBONS_DEMO",
    }:
        coco = [row for row in out if _is_gr_coconut_shell(row)]
        if coco:
            return coco
    return out


def get_raw_material_type(
    db: Session, tenant: TenantContext, product_id: UUID
) -> AcRawMaterialTypeOut:
    repo = _repo(db, tenant)
    product = repo.get_by_pk(Product, Product.product_id, product_id)
    typed = _type_from_product(db, tenant, product)
    if typed is None:
        ptype = (product.product_type or "").upper()
        code = (product.product_code or "").upper()
        if ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-"):
            return _legacy_type_out(db, tenant, product)
        raise NotFoundError(f"Raw material type {product_id} not found")
    return typed


def mark_raw_material_type_obsolete(
    db: Session, tenant: TenantContext, product_id: UUID
) -> AcRawMaterialTypeOut:
    repo = _repo(db, tenant)
    raw = repo.get_by_pk(Product, Product.product_id, product_id)
    typed = get_raw_material_type(db, tenant, product_id)

    if _product_is_obsolete(raw):
        return typed

    raw.status = "OBSOLETE"
    meta = _product_meta(raw)
    meta = {
        **meta,
        "ac_raw_material_type": True,
        "obsolete": True,
        "obsolete_at": meta.get("obsolete_at") or datetime.now(timezone.utc).isoformat(),
    }
    _set_product_metadata(raw, meta)
    raw.product_type = "RAW_MATERIAL"
    repo.db.commit()
    repo.db.refresh(raw)

    updated = _type_from_product(db, tenant, raw)
    if updated is None:
        raise ValidationError("Failed to mark raw material type obsolete")
    return updated


def assert_raw_material_active_for_inward(db: Session, tenant: TenantContext, product_id: UUID) -> None:
    repo = _repo(db, tenant)
    product = repo.get_by_pk(Product, Product.product_id, product_id)
    if _product_is_obsolete(product):
        raise ValidationError(
            f"Raw material '{product.product_name}' ({product.product_code}) is obsolete "
            "and cannot be used for new inward receipts. Add or select an active raw material type."
        )


def create_raw_material_type(
    db: Session, tenant: TenantContext, payload: AcRawMaterialTypeCreate
) -> AcRawMaterialTypeOut:
    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)

    raw_code = resolve_ac_business_code(
        db, provided=payload.product_code, entity="ac_raw_product", tenant_id=tenant.tenant_id
    )
    fg_code = resolve_ac_business_code(
        db, provided=payload.finished_product_code, entity="ac_finished_product", tenant_id=tenant.tenant_id
    )
    routing_code = resolve_ac_business_code(
        db, provided=payload.routing_code, entity="ac_routing", tenant_id=tenant.tenant_id
    )

    fg_name = (payload.finished_product_name or payload.product_name).strip()
    if not fg_name:
        raise ValidationError("Finished product name is required")
    shop_ops = [
        op for op in (payload.operations or []) if not ac_process_rules.is_kiln_feed_bag_qc_step(op)
    ]
    if not shop_ops:
        raise ValidationError("At least one routing operation is required")
    shop_params = [
        p
        for p in (payload.process_parameters or [])
        if not ac_process_rules.is_kiln_feed_bag_qc_parameter(p)
    ]

    finished = None
    try:
        finished = repo.get_by_code(Product, Product.product_code, fg_code)
    except NotFoundError:
        finished_out = mes_core_entities.create_product(
            db,
            tenant,
            ProductCreate(
                product_code=fg_code,
                product_name=fg_name,
                product_type="FINISHED_GOOD",
                uom="KG",
            ),
        )
        finished = repo.get_by_pk(Product, Product.product_id, finished_out.product_id)

    routing_out = mes_core_entities.create_routing_with_operations(
        db,
        tenant,
        RoutingWithOperationsCreate(
            routing_code=routing_code,
            product_id=finished.product_id,
            routing_version="1",
            process_family="ACTIVATED_CARBON",
            operations=[
                RoutingOperationCreate(
                    operation_code=op.operation_code,
                    operation_sequence=op.operation_sequence,
                    operation_name=op.operation_name,
                    process_code=op.process_step,
                    process_type=op.process_step,
                )
                for op in shop_ops
            ],
        ),
    )
    routing_id = routing_out.routing.routing_id
    routing_code = routing_out.routing.routing_code
    _sync_routing_operations(db, tenant, routing_id, shop_ops)

    type_meta = {
        "ac_raw_material_type": True,
        "finished_product_id": str(finished.product_id),
        "finished_product_code": fg_code,
        "finished_product_name": fg_name,
        "routing_id": str(routing_id),
        "routing_code": routing_code,
        "operations": _operations_from_routing(db, tenant, routing_id),
        "inbound_operations": [op.model_dump() for op in payload.inbound_operations],
        "process_parameters": [p.model_dump() for p in shop_params],
    }

    try:
        raw = repo.get_by_code(Product, Product.product_code, raw_code)
        raw.product_name = payload.product_name.strip()
        raw.product_type = "RAW_MATERIAL"
        _set_product_metadata(raw, {**_product_meta(raw), **type_meta})
        repo.db.commit()
        repo.db.refresh(raw)
    except NotFoundError:
        raw_out = mes_core_entities.create_product(
            db,
            tenant,
            ProductCreate(
                product_code=raw_code,
                product_name=payload.product_name.strip(),
                product_type="RAW_MATERIAL",
                uom="KG",
            ),
        )
        raw = repo.get_by_pk(Product, Product.product_id, raw_out.product_id)
        _set_product_metadata(raw, type_meta)
        repo.db.commit()
        repo.db.refresh(raw)

    typed = _type_from_product(db, tenant, raw)
    if typed is None:
        raise ValidationError("Failed to persist raw material type")
    return typed


def update_raw_material_type(
    db: Session,
    tenant: TenantContext,
    product_id: UUID,
    payload: AcRawMaterialTypeUpdate,
) -> AcRawMaterialTypeOut:
    repo = _repo(db, tenant)
    raw = repo.get_by_pk(Product, Product.product_id, product_id)
    meta = _product_meta(raw)

    if _product_is_obsolete(raw):
        raise ValidationError(
            f"Raw material '{raw.product_name}' is obsolete and cannot be edited. "
            "Add a new raw material type for future production."
        )

    usage = raw_material_usage(db, tenant, product_id)
    routing_locked = usage.get("kiln_process_started") or usage.get("dispatch_completed")

    if payload.product_name:
        raw.product_name = payload.product_name.strip()

    finished_id = _uuid_or_none(meta.get("finished_product_id"))
    if payload.finished_product_name and finished_id:
        finished = repo.get_by_pk(Product, Product.product_id, finished_id)
        finished.product_name = payload.finished_product_name.strip()
        meta["finished_product_name"] = finished.product_name

    if payload.operations is not None:
        routing_id = _uuid_or_none(meta.get("routing_id"))
        current_ops = (
            _operations_from_routing(db, tenant, routing_id)
            if routing_id
            else (meta.get("operations") or [])
        )
        shop_ops = [
            op
            for op in payload.operations
            if not ac_process_rules.is_kiln_feed_bag_qc_step(op)
        ]
        hidden_qc = [
            AcRawMaterialTypeOperation(
                operation_sequence=int(row.get("operation_sequence") or 1),
                operation_name=str(row.get("operation_name") or row.get("operation_code") or "Kiln feed"),
                operation_code=str(row.get("operation_code") or ""),
                process_step=str(row.get("process_step") or "KILN_FEED"),
                is_mandatory=row.get("is_mandatory", True),
            )
            for row in current_ops
            if (
                isinstance(row, dict)
                and ac_process_rules.is_kiln_feed_bag_qc_step(row)
                and str(row.get("operation_code") or "").strip()
            )
        ]
        sync_ops = shop_ops + hidden_qc
        if usage.get("dispatch_completed"):
            raise ValidationError(
                "This raw material has been dispatched. Shop-floor process steps cannot be changed."
            )
        if routing_locked and _operation_codes(current_ops) != _operation_codes(sync_ops):
            raise ValidationError(
                "Kiln production has started — you can reorder existing process steps, "
                "but cannot add or remove them."
            )
        if not routing_id:
            routing_id, routing_code, finished = _bootstrap_routing_for_legacy_type(
                db,
                tenant,
                raw,
                meta,
                sync_ops,
                finished_product_name=payload.finished_product_name,
            )
            meta["routing_id"] = str(routing_id)
            meta["routing_code"] = routing_code
            meta["finished_product_id"] = str(finished.product_id)
            meta["finished_product_code"] = finished.product_code
            meta["finished_product_name"] = finished.product_name
        _sync_routing_operations(db, tenant, routing_id, sync_ops)
        meta["operations"] = _operations_from_routing(db, tenant, routing_id)

    if payload.inbound_operations is not None:
        if usage.get("dispatch_completed"):
            raise ValidationError(
                "Inbound prep steps cannot be changed after dispatch has completed."
            )
        meta["inbound_operations"] = [op.model_dump() for op in payload.inbound_operations]

    if payload.process_parameters is not None and not routing_locked:
        meta["process_parameters"] = [
            p.model_dump()
            for p in payload.process_parameters
            if not ac_process_rules.is_kiln_feed_bag_qc_parameter(p)
        ]

    if meta.get("ac_raw_material_type") or (raw.product_type or "").upper() in (
        "RAW_MATERIAL",
        "RAW",
    ):
        meta["ac_raw_material_type"] = True

    _set_product_metadata(raw, meta)
    raw.product_type = "RAW_MATERIAL"
    repo.db.commit()
    repo.db.refresh(raw)

    typed = _type_from_product(db, tenant, raw)
    if typed is None:
        raise ValidationError("Failed to update raw material type")
    return typed


def ensure_missing_process_parameters(
    db: Session,
    tenant: TenantContext,
    product_id: UUID,
    extras: list[AcRawMaterialProcessParameter],
) -> AcRawMaterialTypeOut:
    """Append missing attribute keys only — does not change operations or existing fields."""
    repo = _repo(db, tenant)
    raw = repo.get_by_pk(Product, Product.product_id, product_id)
    meta = _product_meta(raw)
    current = list(meta.get("process_parameters") or [])
    have = {
        str(row.get("key") or row.get("parameter_code") or "").strip().lower()
        for row in current
        if isinstance(row, dict)
    }
    added = 0
    for extra in extras:
        payload = extra.model_dump() if hasattr(extra, "model_dump") else dict(extra)
        key = str(payload.get("key") or payload.get("parameter_code") or "").strip().lower()
        if not key or key in have:
            continue
        current.append(payload)
        have.add(key)
        added += 1
    if added:
        meta["process_parameters"] = current
        meta["ac_raw_material_type"] = True
        _set_product_metadata(raw, meta)
        repo.db.commit()
        repo.db.refresh(raw)
    typed = _type_from_product(db, tenant, raw)
    if typed is None:
        raise ValidationError("Failed to add process parameters")
    return typed
