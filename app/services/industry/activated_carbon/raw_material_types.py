"""Activated Carbon raw material type master — product + routing bundle."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.master import Product
from app.schemas.mes_core.schemas import (
    AcRawMaterialTypeCreate,
    AcRawMaterialTypeOut,
    ProductCreate,
    RoutingOperationCreate,
    RoutingWithOperationsCreate,
)
from app.services.industry.activated_carbon.codes import (
    resolve_ac_business_code,
    sync_ac_sequences,
)
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _type_from_product(product: Product) -> Optional[AcRawMaterialTypeOut]:
    meta = product.metadata_ if isinstance(product.metadata_, dict) else {}
    if not meta.get("ac_raw_material_type"):
        return None
    return AcRawMaterialTypeOut(
        product_id=product.product_id,
        product_code=product.product_code,
        product_name=product.product_name,
        finished_product_code=meta.get("finished_product_code"),
        finished_product_name=meta.get("finished_product_name"),
        finished_product_id=_uuid_or_none(meta.get("finished_product_id")),
        routing_code=meta.get("routing_code"),
        routing_id=_uuid_or_none(meta.get("routing_id")),
        operations=meta.get("operations") or [],
        process_parameters=meta.get("process_parameters") or [],
    )


def _uuid_or_none(value) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def list_raw_material_types(
    db: Session, tenant: TenantContext
) -> List[AcRawMaterialTypeOut]:
    rows = _repo(db, tenant).query(Product).order_by(Product.product_code).all()
    out: list[AcRawMaterialTypeOut] = []
    for row in rows:
        typed = _type_from_product(row)
        if typed:
            out.append(typed)
            continue
        ptype = (row.product_type or "").upper()
        code = (row.product_code or "").upper()
        if ptype in ("RAW_MATERIAL", "RAW") or code.startswith("RAW-"):
            out.append(
                AcRawMaterialTypeOut(
                    product_id=row.product_id,
                    product_code=row.product_code,
                    product_name=row.product_name,
                    finished_product_code=None,
                    operations=[],
                    process_parameters=[],
                )
            )
    return out


def create_raw_material_type(
    db: Session, tenant: TenantContext, payload: AcRawMaterialTypeCreate
) -> AcRawMaterialTypeOut:
    sync_ac_sequences(db, tenant.tenant_id)
    repo = _repo(db, tenant)

    raw_code = resolve_ac_business_code(
        db, provided=payload.product_code, entity="ac_raw_product"
    )
    fg_code = resolve_ac_business_code(
        db, provided=payload.finished_product_code, entity="ac_finished_product"
    )
    routing_code = resolve_ac_business_code(
        db, provided=payload.routing_code, entity="ac_routing"
    )

    fg_name = (payload.finished_product_name or payload.product_name).strip()
    if not fg_name:
        raise ValidationError("Finished product name is required")

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
                for op in payload.operations
            ],
        ),
    )
    routing_id = routing_out.routing.routing_id
    routing_code = routing_out.routing.routing_code

    type_meta = {
        "ac_raw_material_type": True,
        "finished_product_id": str(finished.product_id),
        "finished_product_code": fg_code,
        "finished_product_name": fg_name,
        "routing_id": str(routing_id),
        "routing_code": routing_code,
        "operations": [op.model_dump() for op in payload.operations],
        "process_parameters": [p.model_dump() for p in payload.process_parameters],
    }

    try:
        raw = repo.get_by_code(Product, Product.product_code, raw_code)
        raw.product_name = payload.product_name.strip()
        raw.product_type = "RAW_MATERIAL"
        raw.metadata_ = {**(raw.metadata_ or {}), **type_meta}
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
        raw.metadata_ = type_meta
        repo.db.commit()
        repo.db.refresh(raw)

    typed = _type_from_product(raw)
    if typed is None:
        raise ValidationError("Failed to persist raw material type")
    return typed
