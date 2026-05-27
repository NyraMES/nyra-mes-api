"""Routing routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.common import MessageResponse
from app.schemas.routing import (
    OperationResourceRequirementCreate,
    OperationResourceRequirementOut,
    PartRoutingOut,
    RoutingCreate,
    RoutingOperationCreate,
    RoutingOperationEntryCreate,
    RoutingOperationOut,
    RoutingOperationUpdate,
    RoutingOut,
    RoutingWithOperationsCreate,
    RoutingWithOperationsOut,
)
from app.services import routing_service

router = APIRouter(tags=[Tags.ROUTING])


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get(
    "/routings",
    response_model=List[RoutingOut],
    summary="List all routings",
)
def list_routings(db: Session = Depends(get_db)):
    return routing_service.list_routings(db)


@router.get(
    "/routing/{routing_id}",
    response_model=RoutingOut,
    summary="Get a routing by ID",
)
def get_routing(routing_id: str, db: Session = Depends(get_db)):
    return routing_service.get_routing(db, routing_id)


@router.get(
    "/routing/{routing_id}/operations",
    response_model=List[RoutingOperationOut],
    summary="List the operations of a routing (sequenced)",
)
def list_routing_operations(routing_id: str, db: Session = Depends(get_db)):
    return routing_service.list_operations(db, routing_id)


@router.get(
    "/operation/{operation_id}/requirements",
    response_model=List[OperationResourceRequirementOut],
    summary="List the resource requirements of a routing operation",
)
def list_operation_requirements(operation_id: str, db: Session = Depends(get_db)):
    return routing_service.list_requirements(db, operation_id)


@router.get(
    "/part/{part_id}/routings",
    response_model=List[RoutingOut],
    summary="List routings defined for a part",
)
def list_routings_for_part(part_id: str, db: Session = Depends(get_db)):
    return routing_service.list_routings_for_part(db, part_id)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

@router.post(
    "/routing",
    response_model=RoutingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a routing for a part (no operations yet)",
)
def create_routing(payload: RoutingCreate, db: Session = Depends(get_db)):
    return routing_service.create_routing(db, payload)


@router.post(
    "/routing-operation",
    response_model=RoutingOperationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a single operation to an existing routing",
)
def create_operation(payload: RoutingOperationCreate, db: Session = Depends(get_db)):
    return routing_service.create_operation(db, payload)


@router.post(
    "/operation-resource-requirement",
    response_model=OperationResourceRequirementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a resource requirement (material/machine/tool/workforce) to an operation",
)
def add_resource_requirement(
    payload: OperationResourceRequirementCreate, db: Session = Depends(get_db)
):
    return routing_service.add_requirement(db, payload)


@router.post(
    "/routing-with-operations",
    response_model=RoutingWithOperationsOut,
    status_code=status.HTTP_201_CREATED,
    summary="Atomically create a routing and all its operations in one call (used by the Routing Master UI)",
)
def create_routing_with_operations(
    payload: RoutingWithOperationsCreate, db: Session = Depends(get_db)
):
    return routing_service.create_routing_with_operations(db, payload)


# ---------------------------------------------------------------------------
# Lot-side route materialisation (unchanged)
# ---------------------------------------------------------------------------

@router.get(
    "/lot/{lot_id}/routing-plan",
    summary=(
        "Preview the active routing for a lot's part, including new operations "
        "and whether work orders have been generated"
    ),
)
def lot_routing_plan(lot_id: str, db: Session = Depends(get_db)):
    return routing_service.get_lot_routing_plan(db, lot_id)


@router.post(
    "/lot/{lot_id}/generate-route",
    summary="Auto-load the active routing for the lot's part and materialise the execution plan as work orders",
)
def generate_lot_route(lot_id: str, db: Session = Depends(get_db)):
    operations, feasibility = routing_service.generate_lot_route(db, lot_id)
    return {
        "message": "Route generated for lot",
        "lot_id": lot_id,
        "operation_count": len(operations),
        "operations": operations,
        "feasibility": feasibility.model_dump(),
    }


# ---------------------------------------------------------------------------
# Route entry APIs (REST-style aliases — existing routes above unchanged)
# ---------------------------------------------------------------------------

@router.post(
    "/routings",
    response_model=RoutingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a routing for a part (route entry)",
)
def create_routing_entry(payload: RoutingCreate, db: Session = Depends(get_db)):
    return routing_service.create_routing(db, payload)


@router.post(
    "/routings/{routing_id}/operations",
    response_model=RoutingOperationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an operation step to a routing",
)
def add_routing_operation(
    routing_id: str,
    payload: RoutingOperationEntryCreate,
    db: Session = Depends(get_db),
):
    return routing_service.add_operation_to_routing(db, routing_id, payload)


@router.put(
    "/routing-operations/{routing_operation_id}",
    response_model=RoutingOperationOut,
    summary="Update a routing operation",
)
def update_routing_operation(
    routing_operation_id: str,
    payload: RoutingOperationUpdate,
    db: Session = Depends(get_db),
):
    return routing_service.update_routing_operation(
        db, routing_operation_id, payload
    )


@router.delete(
    "/routing-operations/{routing_operation_id}",
    response_model=MessageResponse,
    summary="Delete a routing operation",
)
def delete_routing_operation(
    routing_operation_id: str, db: Session = Depends(get_db)
):
    routing_service.delete_routing_operation(db, routing_operation_id)
    return MessageResponse(
        message=f"Routing operation '{routing_operation_id}' deleted"
    )
