"""Workspace-scoped routing customization — template copy + operation CRUD."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.master import (
    OperationResourceRequirement,
    Resource,
    Routing,
    RoutingOperation,
    RoutingOperationParameter,
)
from app.schemas.mes_core.schemas import (
    ActiveRoutingOut,
    CopyRoutingFromTemplateRequest,
    OperationResourceRequirementCreate,
    OperationResourceRequirementOut,
    OperationResourceRequirementsSet,
    RoutingOperationCreateRequest,
    RoutingOperationDetailOut,
    RoutingOperationParameterCreate,
    RoutingOperationParameterOut,
    RoutingOperationParameterUpdate,
    RoutingOperationSequencePatch,
    RoutingOperationUpdateRequest,
)
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.ids import resolve_business_code


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _ensure_workspace(tenant: TenantContext) -> None:
    if tenant.workspace_id is None:
        raise ValidationError(
            "Workspace context is required (send X-Workspace-Code header)"
        )


def _ensure_routing_customization_allowed(tenant: TenantContext) -> None:
    _ensure_workspace(tenant)
    # TODO: require ROUTING_CONFIGURATION capability once seeded for all templates.
    caps = set(tenant.enabled_capabilities or ())
    if caps and "ROUTING_CONFIGURATION" in caps and not tenant.has_capability(
        "ROUTING_CONFIGURATION"
    ):
        raise ForbiddenError("ROUTING_CONFIGURATION capability is required")


def _assert_mutable_routing(routing: Routing, tenant: TenantContext) -> None:
    if getattr(routing, "is_template_route", False):
        raise ForbiddenError("Industry template routes cannot be modified")
    if routing.workspace_id is None:
        raise ForbiddenError("Only workspace-scoped routes can be customized")
    if tenant.workspace_id and routing.workspace_id != tenant.workspace_id:
        raise ForbiddenError("Route belongs to a different workspace")


def _find_industry_template_route(
    db: Session, industry_template_code: str, template_routing_code: str
) -> Routing:
    row = (
        db.query(Routing)
        .filter(
            Routing.industry_template_code == industry_template_code,
            Routing.is_template_route.is_(True),
            Routing.routing_code == template_routing_code,
            Routing.is_active.is_(True),
        )
        .first()
    )
    if not row:
        raise NotFoundError(
            f"Template route '{template_routing_code}' not found for "
            f"industry '{industry_template_code}'"
        )
    return row


def _requirement_out(
    row: OperationResourceRequirement, resource: Optional[Resource]
) -> OperationResourceRequirementOut:
    return OperationResourceRequirementOut(
        requirement_id=row.requirement_id,
        routing_operation_id=row.routing_operation_id,
        resource_id=row.resource_id,
        resource_code=resource.resource_code if resource else "",
        resource_name=resource.resource_name if resource else "",
        resource_type=resource.resource_type if resource else "",
        requirement_type=row.requirement_type,
        quantity=row.quantity or Decimal("1"),
        uom=row.uom or "EA",
    )


def _requirements_by_operation(
    repo: TenantRepository, operation_ids: list
) -> dict:
    if not operation_ids:
        return {}
    rows = (
        repo.query(OperationResourceRequirement)
        .filter(OperationResourceRequirement.routing_operation_id.in_(operation_ids))
        .all()
    )
    resource_ids = {row.resource_id for row in rows}
    resources = {
        r.resource_id: r
        for r in repo.query(Resource)
        .filter(Resource.resource_id.in_(resource_ids))
        .all()
    }
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.routing_operation_id, []).append(
            _requirement_out(row, resources.get(row.resource_id))
        )
    return grouped


def _parameters_by_operation(
    repo: TenantRepository, operation_ids: list
) -> dict:
    if not operation_ids:
        return {}
    rows = (
        repo.query_workspace_strict(RoutingOperationParameter)
        .filter(
            RoutingOperationParameter.routing_operation_id.in_(operation_ids),
            RoutingOperationParameter.is_active.is_(True),
        )
        .order_by(RoutingOperationParameter.display_order.nulls_last())
        .all()
    )
    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.routing_operation_id, []).append(
            RoutingOperationParameterOut.model_validate(row)
        )
    return grouped


def _operation_detail(
    row: RoutingOperation,
    requirements: Optional[list[OperationResourceRequirementOut]] = None,
    parameters: Optional[list[RoutingOperationParameterOut]] = None,
) -> RoutingOperationDetailOut:
    seq = row.operation_seq if row.operation_seq is not None else row.operation_sequence
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return RoutingOperationDetailOut(
        routing_operation_id=row.routing_operation_id,
        tenant_id=row.tenant_id,
        workspace_id=row.workspace_id,
        routing_id=row.routing_id,
        operation_code=row.operation_code,
        operation_sequence=row.operation_sequence,
        operation_seq=seq,
        operation_name=row.operation_name,
        operation_type=row.operation_type or meta.get("operation_type"),
        standard_cycle_min=row.standard_cycle_min,
        is_quality_gate=bool(row.is_quality_gate),
        is_feasibility_gate=bool(row.is_feasibility_gate),
        is_active=bool(row.is_active),
        is_customized=bool(row.is_customized),
        source_template_operation_code=row.source_template_operation_code,
        process_id=meta.get("process_step") or meta.get("process_id"),
        resource_requirements=requirements or [],
        parameters=parameters or [],
    )


def _routing_detail(
    db: Session, tenant: TenantContext, routing: Routing
) -> ActiveRoutingOut:
    repo = _repo(db, tenant)
    ops = (
        repo.query_workspace_strict(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == routing.routing_id,
            RoutingOperation.is_active.is_(True),
        )
        .order_by(RoutingOperation.operation_sequence)
        .all()
        if routing.workspace_id
        else repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )
    op_ids = [o.routing_operation_id for o in ops]
    req_map = _requirements_by_operation(repo, op_ids)
    param_map = _parameters_by_operation(repo, op_ids)
    return ActiveRoutingOut(
        routing_id=routing.routing_id,
        tenant_id=routing.tenant_id,
        workspace_id=routing.workspace_id,
        routing_code=routing.routing_code,
        product_id=routing.product_id,
        routing_version=routing.routing_version,
        process_family=routing.process_family,
        is_active=routing.is_active,
        industry_template_code=routing.industry_template_code,
        source_template_code=routing.source_template_code,
        is_template_route=bool(routing.is_template_route),
        is_template_copy=bool(routing.is_template_copy),
        is_customized=bool(routing.is_customized),
        operations=[
            _operation_detail(
                o,
                req_map.get(o.routing_operation_id, []),
                param_map.get(o.routing_operation_id, []),
            )
            for o in ops
        ],
    )


def copy_routing_from_template(
    db: Session,
    tenant: TenantContext,
    payload: CopyRoutingFromTemplateRequest,
) -> ActiveRoutingOut:
    _ensure_routing_customization_allowed(tenant)
    repo = _repo(db, tenant)
    template_code = payload.template_routing_code

    existing = (
        repo.query_workspace_strict(Routing)
        .filter(
            Routing.is_template_copy.is_(True),
            Routing.source_template_code == template_code,
            Routing.is_active.is_(True),
        )
        .first()
    )
    if existing:
        return _routing_detail(db, tenant, existing)

    template = _find_industry_template_route(
        db, tenant.industry_template_code, template_code
    )
    template_ops = (
        db.query(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == template.routing_id,
            RoutingOperation.is_active.is_(True),
        )
        .order_by(RoutingOperation.operation_sequence)
        .all()
    )

    ws_suffix = (tenant.workspace_code or "WS")[:32]
    workspace_routing_code = f"{template_code}-{ws_suffix}"[:64]
    copy_product_id = template.product_id
    if copy_product_id is None:
        fallback = (
            repo.query(Routing)
            .filter(
                Routing.product_id.isnot(None),
                Routing.is_active.is_(True),
            )
            .first()
        )
        copy_product_id = fallback.product_id if fallback else None
    if copy_product_id is None:
        raise ValidationError(
            "Template route has no product_id and no workspace product routing exists — "
            "seed finished product routing (e.g. RT-AC-8x30-V1) first"
        )
    routing = repo.add(
        Routing(
            routing_code=workspace_routing_code,
            product_id=copy_product_id,
            routing_version=template.routing_version,
            process_family=template.process_family,
            is_active=True,
            industry_template_code=tenant.industry_template_code,
            source_template_code=template_code,
            is_template_route=False,
            is_template_copy=True,
            is_customized=False,
        )
    )
    repo.db.flush()

    op_id_map: dict = {}
    for top in template_ops:
        seq = top.operation_seq if top.operation_seq is not None else top.operation_sequence
        meta = top.metadata_ if isinstance(top.metadata_, dict) else {}
        new_op = repo.add(
            RoutingOperation(
                routing_id=routing.routing_id,
                operation_code=top.operation_code,
                operation_sequence=seq,
                operation_seq=seq,
                operation_name=top.operation_name,
                operation_type=top.operation_type,
                standard_cycle_min=top.standard_cycle_min,
                industry_template_code=tenant.industry_template_code,
                source_template_operation_code=top.operation_code,
                is_quality_gate=top.is_quality_gate,
                is_feasibility_gate=top.is_feasibility_gate,
                is_active=True,
                is_customized=False,
                metadata_=dict(meta),
            )
        )
        repo.db.flush()
        op_id_map[top.routing_operation_id] = new_op.routing_operation_id

    if op_id_map:
        template_reqs = (
            db.query(OperationResourceRequirement)
            .filter(
                OperationResourceRequirement.routing_operation_id.in_(
                    list(op_id_map.keys())
                )
            )
            .all()
        )
        for req in template_reqs:
            new_op_id = op_id_map.get(req.routing_operation_id)
            if not new_op_id:
                continue
            repo.add(
                OperationResourceRequirement(
                    routing_operation_id=new_op_id,
                    resource_id=req.resource_id,
                    requirement_type=req.requirement_type,
                    quantity=req.quantity,
                    uom=req.uom,
                    metadata_=dict(req.metadata_ if isinstance(req.metadata_, dict) else {}),
                )
            )

    repo.db.commit()
    repo.db.refresh(routing)
    return _routing_detail(db, tenant, routing)


def get_active_workspace_routing(
    db: Session, tenant: TenantContext
) -> ActiveRoutingOut:
    _ensure_workspace(tenant)
    repo = _repo(db, tenant)
    routing = (
        repo.query_workspace_strict(Routing)
        .filter(
            Routing.is_template_copy.is_(True),
            Routing.is_active.is_(True),
        )
        .order_by(Routing.created_at.desc())
        .first()
    )
    if not routing:
        raise NotFoundError(
            "No active workspace route — copy from template first "
            "(POST /api/routings/copy-from-template)"
        )
    return _routing_detail(db, tenant, routing)


def _get_mutable_operation(
    db: Session, tenant: TenantContext, operation_id: UUID
) -> tuple[RoutingOperation, Routing]:
    repo = _repo(db, tenant)
    op = repo.query_workspace_strict(RoutingOperation).filter(
        RoutingOperation.routing_operation_id == operation_id
    ).first()
    if not op:
        raise NotFoundError(f"Routing operation '{operation_id}' not found")
    routing = repo.query_workspace_strict(Routing).filter(
        Routing.routing_id == op.routing_id
    ).first()
    if not routing:
        raise NotFoundError(f"Routing for operation '{operation_id}' not found")
    _assert_mutable_routing(routing, tenant)
    return op, routing


def add_routing_operation(
    db: Session,
    tenant: TenantContext,
    payload: RoutingOperationCreateRequest,
) -> RoutingOperationDetailOut:
    _ensure_routing_customization_allowed(tenant)
    active = get_active_workspace_routing(db, tenant)
    repo = _repo(db, tenant)
    routing = repo.get_by_pk(Routing, Routing.routing_id, active.routing_id)
    _assert_mutable_routing(routing, tenant)

    seq = payload.operation_seq or payload.operation_sequence
    if seq is None:
        raise ValidationError("operation_seq is required")

    conflict = (
        repo.query_workspace_strict(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == routing.routing_id,
            RoutingOperation.operation_sequence == seq,
            RoutingOperation.is_active.is_(True),
        )
        .first()
    )
    if conflict:
        raise ValidationError(f"Operation sequence {seq} already exists on this route")

    code = payload.operation_code or resolve_business_code(
        db, provided=None, entity="routing_operation"
    )
    op = repo.add(
        RoutingOperation(
            routing_id=routing.routing_id,
            operation_code=code,
            operation_sequence=seq,
            operation_seq=seq,
            operation_name=payload.operation_name,
            operation_type=payload.operation_type,
            standard_cycle_min=payload.standard_cycle_min,
            is_quality_gate=payload.is_quality_gate,
            is_feasibility_gate=payload.is_feasibility_gate,
            is_active=True,
            is_customized=True,
            industry_template_code=tenant.industry_template_code,
            metadata_={"process_step": payload.process_step},
        )
    )
    routing.is_customized = True
    repo.db.commit()
    repo.db.refresh(op)
    return _operation_detail(op)


def update_operation_sequence(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
    payload: RoutingOperationSequencePatch,
) -> RoutingOperationDetailOut:
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)
    new_seq = payload.operation_seq
    if new_seq <= 0:
        raise ValidationError("operation_seq must be positive")

    conflict = (
        repo.query_workspace_strict(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == routing.routing_id,
            RoutingOperation.routing_operation_id != op.routing_operation_id,
            RoutingOperation.operation_sequence == new_seq,
            RoutingOperation.is_active.is_(True),
        )
        .first()
    )
    if conflict:
        old_seq = op.operation_sequence
        conflict.operation_sequence = old_seq
        conflict.operation_seq = old_seq
        conflict.is_customized = True

    op.operation_sequence = new_seq
    op.operation_seq = new_seq
    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()
    repo.db.refresh(op)
    return _operation_detail(op)


def update_routing_operation(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
    payload: RoutingOperationUpdateRequest,
) -> RoutingOperationDetailOut:
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)

    if payload.operation_name is not None:
        op.operation_name = payload.operation_name
    if payload.operation_type is not None:
        op.operation_type = payload.operation_type
    if payload.is_quality_gate is not None:
        op.is_quality_gate = payload.is_quality_gate
    if payload.is_feasibility_gate is not None:
        op.is_feasibility_gate = payload.is_feasibility_gate
    if payload.is_active is not None:
        op.is_active = payload.is_active
    if payload.standard_cycle_min is not None:
        op.standard_cycle_min = payload.standard_cycle_min

    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()
    repo.db.refresh(op)
    return _operation_detail(op)


def delete_routing_operation(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
) -> None:
    """Soft-delete a workspace routing operation (hide from active route)."""
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)

    active_count = (
        repo.query_workspace_strict(RoutingOperation)
        .filter(
            RoutingOperation.routing_id == routing.routing_id,
            RoutingOperation.is_active.is_(True),
        )
        .count()
    )
    if active_count <= 1:
        raise ValidationError("Cannot remove the last operation on the workspace route")

    op.is_active = False
    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()


def add_operation_parameter(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
    payload: RoutingOperationParameterCreate,
) -> RoutingOperationParameterOut:
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)

    row = repo.add(
        RoutingOperationParameter(
            routing_operation_id=op.routing_operation_id,
            parameter_code=payload.parameter_code,
            parameter_name=payload.parameter_name,
            data_type=payload.data_type,
            unit=payload.unit,
            min_value=payload.min_value,
            max_value=payload.max_value,
            is_mandatory=payload.is_mandatory,
            reading_frequency=payload.reading_frequency,
            display_order=payload.display_order,
            is_active=True,
        )
    )
    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()
    repo.db.refresh(row)
    return RoutingOperationParameterOut.model_validate(row)


def update_operation_parameter(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
    parameter_id: UUID,
    payload: RoutingOperationParameterUpdate,
) -> RoutingOperationParameterOut:
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)
    row = (
        repo.query_workspace_strict(RoutingOperationParameter)
        .filter(
            RoutingOperationParameter.id == parameter_id,
            RoutingOperationParameter.routing_operation_id == operation_id,
            RoutingOperationParameter.is_active.is_(True),
        )
        .first()
    )
    if not row:
        raise NotFoundError(f"Parameter '{parameter_id}' not found on operation '{operation_id}'")

    if payload.parameter_name is not None:
        row.parameter_name = payload.parameter_name
    if payload.data_type is not None:
        row.data_type = payload.data_type
    if payload.unit is not None:
        row.unit = payload.unit
    if payload.min_value is not None:
        row.min_value = payload.min_value
    if payload.max_value is not None:
        row.max_value = payload.max_value
    if payload.is_mandatory is not None:
        row.is_mandatory = payload.is_mandatory
    if payload.reading_frequency is not None:
        row.reading_frequency = payload.reading_frequency
    if payload.display_order is not None:
        row.display_order = payload.display_order

    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()
    repo.db.refresh(row)
    return RoutingOperationParameterOut.model_validate(row)


def delete_operation_parameter(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
    parameter_id: UUID,
) -> None:
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)
    row = (
        repo.query_workspace_strict(RoutingOperationParameter)
        .filter(
            RoutingOperationParameter.id == parameter_id,
            RoutingOperationParameter.routing_operation_id == operation_id,
            RoutingOperationParameter.is_active.is_(True),
        )
        .first()
    )
    if not row:
        raise NotFoundError(f"Parameter '{parameter_id}' not found on operation '{operation_id}'")

    row.is_active = False
    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()


def list_operation_parameters(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
) -> List[RoutingOperationParameterOut]:
    _ensure_workspace(tenant)
    repo = _repo(db, tenant)
    op = repo.query_workspace_strict(RoutingOperation).filter(
        RoutingOperation.routing_operation_id == operation_id
    ).first()
    if not op:
        raise NotFoundError(f"Routing operation '{operation_id}' not found")

    rows = (
        repo.query_workspace_strict(RoutingOperationParameter)
        .filter(
            RoutingOperationParameter.routing_operation_id == operation_id,
            RoutingOperationParameter.is_active.is_(True),
        )
        .order_by(RoutingOperationParameter.display_order.nulls_last())
        .all()
    )
    return [RoutingOperationParameterOut.model_validate(r) for r in rows]


_VALID_REQUIREMENT_TYPES = frozenset({"PRIMARY", "TOOL", "LABOR", "SECONDARY", "MATERIAL"})
_REQUIREMENT_RESOURCE_TYPES = {
    "PRIMARY": frozenset({"MACHINE", "WORKCELL", "LINE"}),
    "TOOL": frozenset({"TOOL"}),
    "SECONDARY": frozenset({"TOOL"}),
    "LABOR": frozenset({"LABOR"}),
    "MATERIAL": frozenset({"RAW_MATERIAL", "MATERIAL", "FINISHED"}),
}


def _validate_requirement_payload(
    repo: TenantRepository, payload: OperationResourceRequirementCreate
) -> Resource:
    req_type = (payload.requirement_type or "").upper()
    if req_type not in _VALID_REQUIREMENT_TYPES:
        raise ValidationError(
            f"requirement_type must be one of: {', '.join(sorted(_VALID_REQUIREMENT_TYPES))}"
        )
    resource = (
        repo.query(Resource).filter(Resource.resource_id == payload.resource_id).first()
    )
    if not resource:
        raise NotFoundError(f"Resource '{payload.resource_id}' not found")
    allowed = _REQUIREMENT_RESOURCE_TYPES.get(req_type, frozenset())
    rtype = (resource.resource_type or "").upper()
    if allowed and rtype not in allowed:
        raise ValidationError(
            f"Resource '{resource.resource_code}' is type {resource.resource_type}; "
            f"{req_type} requires {', '.join(sorted(allowed))}"
        )
    return resource


def list_operation_resource_requirements(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
) -> List[OperationResourceRequirementOut]:
    _ensure_workspace(tenant)
    repo = _repo(db, tenant)
    op = repo.query_workspace_strict(RoutingOperation).filter(
        RoutingOperation.routing_operation_id == operation_id
    ).first()
    if not op:
        raise NotFoundError(f"Routing operation '{operation_id}' not found")
    return _requirements_by_operation(repo, [operation_id]).get(operation_id, [])


def set_operation_resource_requirements(
    db: Session,
    tenant: TenantContext,
    operation_id: UUID,
    payload: OperationResourceRequirementsSet,
) -> List[OperationResourceRequirementOut]:
    _ensure_routing_customization_allowed(tenant)
    op, routing = _get_mutable_operation(db, tenant, operation_id)
    repo = _repo(db, tenant)

    primary_count = sum(
        1
        for item in payload.requirements
        if (item.requirement_type or "").upper() == "PRIMARY"
    )
    if primary_count > 1:
        raise ValidationError("At most one PRIMARY machine requirement per operation")

    validated: list[tuple[OperationResourceRequirementCreate, Resource]] = []
    seen: set[tuple] = set()
    for item in payload.requirements:
        resource = _validate_requirement_payload(repo, item)
        key = (item.resource_id, (item.requirement_type or "").upper())
        if key in seen:
            continue
        seen.add(key)
        validated.append((item, resource))

    (
        repo.query(OperationResourceRequirement)
        .filter(OperationResourceRequirement.routing_operation_id == operation_id)
        .delete(synchronize_session=False)
    )

    for item, _resource in validated:
        repo.add(
            OperationResourceRequirement(
                routing_operation_id=op.routing_operation_id,
                resource_id=item.resource_id,
                requirement_type=(item.requirement_type or "").upper(),
                quantity=item.quantity,
                uom=item.uom or "EA",
            )
        )

    op.is_customized = True
    routing.is_customized = True
    repo.db.commit()
    return list_operation_resource_requirements(db, tenant, operation_id)
