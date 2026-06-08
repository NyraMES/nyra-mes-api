"""Shared routing / machine resolution for scheduling and feasibility."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from app.models.mes_core import (
    CustomerOrderLine,
    Equipment,
    OperationResourceRequirement,
    Product,
    ProductionLot,
    ProductionOrder,
    Resource,
    Routing,
    RoutingOperation,
)
from app.services.mes_core.base import TenantRepository

AVAILABLE_STATUSES = frozenset({"ACTIVE", "AVAILABLE", "IDLE", "READY"})


def is_resource_available(status: Optional[str]) -> bool:
    return (status or "").upper() in AVAILABLE_STATUSES


def _ordered_routing_operations(
    operations: list[RoutingOperation],
) -> list[RoutingOperation]:
    """Stable shop-floor order: sequence, then operation_seq, then code."""
    return sorted(
        operations,
        key=lambda op: (
            int(op.operation_sequence or op.operation_seq or 0),
            op.operation_code or "",
        ),
    )


def load_lot_routing(
    repo: TenantRepository, lot: ProductionLot
) -> Tuple[Optional[Product], Optional[Routing], list[RoutingOperation], float]:
    """Return product, active routing, ordered operations, and lot quantity."""
    po = repo.get_by_pk(
        ProductionOrder,
        ProductionOrder.production_order_id,
        lot.production_order_id,
    )
    line = repo.get_by_pk(
        CustomerOrderLine,
        CustomerOrderLine.order_line_id,
        po.order_line_id,
    )
    product = repo.get_by_pk(Product, Product.product_id, line.product_id)

    # Product routing first (same as schedule-plan) — workspace template copies are
    # menu/process reference only and must not override RT-AC-* shop-floor routes.
    routing = (
        repo.query(Routing)
        .filter(Routing.product_id == product.product_id, Routing.is_active.is_(True))
        .order_by(Routing.routing_version.desc())
        .first()
    )
    if not routing and repo.workspace_id is not None:
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
        return product, None, [], float(lot.lot_quantity)

    operations = _ordered_routing_operations(
        repo.query(RoutingOperation)
        .filter(RoutingOperation.routing_id == routing.routing_id)
        .all()
    )
    return product, routing, operations, float(lot.lot_quantity)


def resolve_operation_machine(
    repo: TenantRepository, op: RoutingOperation
) -> dict[str, Any]:
    """Resolve suggested machine / work-center for a routing operation."""
    suggested_machine_code: Optional[str] = None
    suggested_machine_name: Optional[str] = None
    suggested_wc_code: Optional[str] = None
    suggested_wc_name: Optional[str] = None
    equipment: Optional[Equipment] = None
    resource: Optional[Resource] = None
    source = "fallback"

    req = (
        repo.query(OperationResourceRequirement)
        .filter(
            OperationResourceRequirement.routing_operation_id == op.routing_operation_id,
            OperationResourceRequirement.requirement_type == "PRIMARY",
        )
        .first()
    )
    if req:
        resource = (
            repo.query(Resource)
            .filter(Resource.resource_id == req.resource_id)
            .first()
        )
        if resource:
            source = "requirement"
            suggested_wc_code = resource.resource_code
            suggested_wc_name = resource.resource_name
            equipment = (
                repo.query(Equipment)
                .filter(Equipment.resource_id == resource.resource_id)
                .order_by(Equipment.equipment_code)
                .first()
            )
            if equipment:
                suggested_machine_code = equipment.equipment_code
                suggested_machine_name = equipment.equipment_name

    if not suggested_machine_code:
        fallback_equip = repo.query(Equipment).order_by(Equipment.equipment_code).first()
        if fallback_equip:
            equipment = fallback_equip
            suggested_machine_code = fallback_equip.equipment_code
            suggested_machine_name = fallback_equip.equipment_name
            if fallback_equip.resource_id and not suggested_wc_code:
                wc = (
                    repo.query(Resource)
                    .filter(Resource.resource_id == fallback_equip.resource_id)
                    .first()
                )
                if wc:
                    resource = wc
                    suggested_wc_code = wc.resource_code
                    suggested_wc_name = wc.resource_name
        elif not suggested_wc_code:
            fallback_res = (
                repo.query(Resource)
                .filter(Resource.resource_type.in_(("MACHINE", "WORKCELL", "LINE")))
                .order_by(Resource.resource_code)
                .first()
            )
            if fallback_res:
                resource = fallback_res
                suggested_machine_code = fallback_res.resource_code
                suggested_machine_name = fallback_res.resource_name
                suggested_wc_code = fallback_res.resource_code
                suggested_wc_name = fallback_res.resource_name

    return {
        "operation_code": op.operation_code,
        "operation_name": op.operation_name,
        "machine_code": suggested_machine_code,
        "machine_name": suggested_machine_name,
        "work_center_code": suggested_wc_code,
        "work_center_name": suggested_wc_name,
        "equipment": equipment,
        "resource": resource,
        "source": source,
    }
