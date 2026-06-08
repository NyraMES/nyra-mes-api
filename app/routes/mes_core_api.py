"""Generic multi-tenant API routes backed by nyra_mes_core.

These live under ``/api/*`` and are industry-agnostic.  Legacy workflow routes
(``/customer``, ``/part``, ``/production``, …) remain on the original database
unchanged — see comments in ``app.main`` where both routers are registered.
"""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.demo_protection import demo_watermark_text, effective_demo_mode, effective_demo_read_only
from app.core.dependencies import get_mes_core_db, get_tenant_context
from app.core.openapi_tags import Tags
from app.core.tenant_context import TenantContext
from app.schemas.feasibility import FeasibilityResponse
from app.schemas.oee import OEEDailySummaryCreate, OEEDailySummaryOut, OEEIntelligenceResponse
from app.schemas.mes_core.schemas import (
    AskNyraRequest,
    AskNyraResponse,
    IntelligenceHubOut,
    CustomerCreate,
    CustomerOrderCreate,
    CustomerOrderCreateResponse,
    CustomerOrderLineCreate,
    CustomerOrderLineOut,
    CustomerOrderOut,
    CustomerOut,
    EquipmentCreate,
    EquipmentOut,
    FeasibilityCheckCreate,
    FeasibilityCheckOut,
    InspectionResultCreateRequest,
    OperationExecutionCreate,
    OperationExecutionOut,
    ProductCreate,
    ProductOut,
    ProductionLotCreate,
    ProductionLotOut,
    ProductionLotSplitRequest,
    ProductionLotSplitResponse,
    ProductionOrderCreate,
    ProductionOrderOut,
    QualityCheckCreate,
    QualityCheckOut,
    ResourceCreate,
    ResourceOut,
    RoutingCreate,
    RoutingOperationCreate,
    RoutingOperationCreateRequest,
    RoutingOperationDetailOut,
    RoutingOperationOut,
    RoutingOperationParameterCreate,
    RoutingOperationParameterOut,
    OperationResourceRequirementOut,
    OperationResourceRequirementsSet,
    RoutingOperationSequencePatch,
    RoutingOperationUpdateRequest,
    ActiveRoutingOut,
    CopyRoutingFromTemplateRequest,
    RoutingOut,
    RoutingWithOperationsCreate,
    RoutingWithOperationsOut,
    ScheduleCreate,
    ScheduleOut,
    SchedulePlanOut,
    FeasibilityGateOut,
    TenantContextOut,
    TripleCreate,
    TripleOut,
)
from app.services.mes_core import ask_nyra as mes_core_ask
from app.services.mes_core import intelligence_hub as mes_core_intelligence
from app.services.mes_core import entities as mes_core_service
from app.services.mes_core import feasibility as mes_core_feasibility
from app.services.mes_core import oee_intelligence as mes_core_oee
from app.schemas.dispatch import DispatchCreate, DispatchOut
from app.schemas.quality import (
    InspectionResultCreate,
    InspectionResultOut,
    NCRCreate,
    NCROut,
)
from app.schemas.schedule import (
    ParameterReadingsAppendRequest,
    WorkOrderCompleteRequest,
    WorkOrderHoldRequest,
    WorkOrderOut,
    WorkOrderStartRequest,
)
from app.services.mes_core import dispatch_workflow as mes_core_dispatch
from app.services.mes_core import execution_workflow as mes_core_execution
from app.services.mes_core import quality_workflow as mes_core_quality
from app.schemas.traceability import TraceabilityResponse
from app.services.mes_core import scheduling as mes_core_scheduling
from app.services.mes_core import traceability_workflow as mes_core_traceability
from app.services.mes_core import routing_customization as mes_core_routing_customization

router = APIRouter(prefix="/api", tags=[Tags.MES_CORE])


@router.get(
    "/context",
    response_model=TenantContextOut,
    summary="Current tenant and industry template",
)
def get_context(tenant: TenantContext = Depends(get_tenant_context)):
    demo_mode = effective_demo_mode(tenant.tenant_code)
    demo_read_only = effective_demo_read_only(tenant.tenant_code)
    return TenantContextOut(
        tenant_id=tenant.tenant_id,
        tenant_code=tenant.tenant_code,
        tenant_name=tenant.tenant_name,
        workspace_id=tenant.workspace_id,
        workspace_code=tenant.workspace_code,
        workspace_name=tenant.workspace_name,
        industry_template_code=tenant.industry_template_code,
        industry_template_name=tenant.industry_template_name,
        module_code=tenant.module_code,
        landing_page=tenant.landing_page,
        ui_module_name=tenant.ui_module_name,
        api_module_name=tenant.api_module_name,
        icon_name=tenant.icon_name,
        dashboard_component=tenant.dashboard_component,
        enabled_capabilities=list(tenant.enabled_capabilities),
        demo_mode=demo_mode,
        demo_read_only=demo_read_only,
        demo_watermark=demo_watermark_text() if demo_mode else None,
    )


@router.get("/health", summary="MES Core health probe")
def mes_core_health():
    return {"status": "ok", "mes_core_enabled": settings.mes_core_enabled}


# --- Customers ---


@router.get("/customers", response_model=List[CustomerOut], summary="List customers")
def list_customers(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_customers(db, tenant)


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerOut,
    summary="Get customer by ID",
)
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_customer(db, tenant, customer_id)


@router.post(
    "/customers",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create customer",
)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_customer(db, tenant, payload)


# --- Products ---


@router.get("/products", response_model=List[ProductOut], summary="List products")
def list_products(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_products(db, tenant)


@router.get(
    "/products/{product_id}",
    response_model=ProductOut,
    summary="Get product by ID",
)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_product(db, tenant, product_id)


@router.post(
    "/products",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create product",
)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_product(db, tenant, payload)


# --- Resources ---


@router.get("/resources", response_model=List[ResourceOut], summary="List resources")
def list_resources(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_resources(db, tenant)


@router.get(
    "/resources/{resource_id}",
    response_model=ResourceOut,
    summary="Get resource by ID",
)
def get_resource(
    resource_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_resource(db, tenant, resource_id)


@router.post(
    "/resources",
    response_model=ResourceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create resource",
)
def create_resource(
    payload: ResourceCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_resource(db, tenant, payload)


# --- Equipment ---


@router.get("/equipment", response_model=List[EquipmentOut], summary="List equipment")
def list_equipment(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_equipment(db, tenant)


@router.get(
    "/equipment/{equipment_id}",
    response_model=EquipmentOut,
    summary="Get equipment by ID",
)
def get_equipment(
    equipment_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_equipment(db, tenant, equipment_id)


@router.post(
    "/equipment",
    response_model=EquipmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create equipment",
)
def create_equipment(
    payload: EquipmentCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_equipment(db, tenant, payload)


# --- Routings ---


@router.get("/routings", response_model=List[RoutingOut], summary="List routings")
def list_routings(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_routings(db, tenant)


@router.post(
    "/routings/copy-from-template",
    response_model=ActiveRoutingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Copy industry template route into active workspace",
)
def copy_routing_from_template(
    payload: CopyRoutingFromTemplateRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.copy_routing_from_template(db, tenant, payload)


@router.get(
    "/routings/active",
    response_model=ActiveRoutingOut,
    summary="Active workspace route for tenant/workspace context",
)
def get_active_routing(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.get_active_workspace_routing(db, tenant)


@router.get(
    "/routings/{routing_id}",
    response_model=RoutingOut,
    summary="Get routing by ID",
)
def get_routing(
    routing_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_routing(db, tenant, routing_id)


@router.post(
    "/routings",
    response_model=RoutingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create routing",
)
def create_routing(
    payload: RoutingCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_routing(db, tenant, payload)


@router.post(
    "/routings/with-operations",
    response_model=RoutingWithOperationsOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create routing with operations (atomic)",
)
def create_routing_with_operations(
    payload: RoutingWithOperationsCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_routing_with_operations(db, tenant, payload)


@router.post(
    "/routing-operations",
    response_model=RoutingOperationDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add operation to active workspace route",
)
def create_routing_operation(
    payload: RoutingOperationCreateRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.add_routing_operation(db, tenant, payload)


@router.patch(
    "/routing-operations/{operation_id}/sequence",
    response_model=RoutingOperationDetailOut,
    summary="Update operation sequence on workspace route",
)
def patch_routing_operation_sequence(
    operation_id: UUID,
    payload: RoutingOperationSequencePatch,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.update_operation_sequence(
        db, tenant, operation_id, payload
    )


@router.put(
    "/routing-operations/{operation_id}",
    response_model=RoutingOperationDetailOut,
    summary="Update workspace routing operation",
)
def update_routing_operation(
    operation_id: UUID,
    payload: RoutingOperationUpdateRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.update_routing_operation(
        db, tenant, operation_id, payload
    )


@router.delete(
    "/routing-operations/{operation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove operation from workspace route",
)
def delete_routing_operation(
    operation_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    mes_core_routing_customization.delete_routing_operation(db, tenant, operation_id)


@router.post(
    "/routing-operations/{operation_id}/parameters",
    response_model=RoutingOperationParameterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add parameter to workspace routing operation",
)
def create_routing_operation_parameter(
    operation_id: UUID,
    payload: RoutingOperationParameterCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.add_operation_parameter(
        db, tenant, operation_id, payload
    )


@router.get(
    "/routing-operations/{operation_id}/parameters",
    response_model=List[RoutingOperationParameterOut],
    summary="List parameters for workspace routing operation",
)
def list_routing_operation_parameters(
    operation_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.list_operation_parameters(
        db, tenant, operation_id
    )


@router.get(
    "/routing-operations/{operation_id}/resource-requirements",
    response_model=List[OperationResourceRequirementOut],
    summary="List resource requirements for a routing operation",
)
def list_routing_operation_resource_requirements(
    operation_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.list_operation_resource_requirements(
        db, tenant, operation_id
    )


@router.put(
    "/routing-operations/{operation_id}/resource-requirements",
    response_model=List[OperationResourceRequirementOut],
    summary="Replace resource requirements for a routing operation",
)
def set_routing_operation_resource_requirements(
    operation_id: UUID,
    payload: OperationResourceRequirementsSet,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_routing_customization.set_operation_resource_requirements(
        db, tenant, operation_id, payload
    )


# --- Customer orders ---


@router.get(
    "/customer-orders",
    response_model=List[CustomerOrderOut],
    summary="List customer orders",
)
def list_customer_orders(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_customer_orders(db, tenant)


@router.post(
    "/customer-orders",
    response_model=CustomerOrderCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create customer order with first line",
)
def create_customer_order(
    payload: CustomerOrderCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_customer_order(db, tenant, payload)


@router.post(
    "/customer-orders/{customer_order_id}/lines",
    response_model=CustomerOrderLineOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add line to customer order",
)
def create_customer_order_line(
    customer_order_id: UUID,
    payload: CustomerOrderLineCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_customer_order_line(
        db, tenant, customer_order_id, payload
    )


# --- Production orders ---


@router.get(
    "/production-orders",
    response_model=List[ProductionOrderOut],
    summary="List production orders",
)
def list_production_orders(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_production_orders(db, tenant)


@router.get(
    "/production-orders/{production_order_id}",
    response_model=ProductionOrderOut,
    summary="Get production order by ID",
)
def get_production_order(
    production_order_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_production_order(db, tenant, production_order_id)


@router.get(
    "/production-orders/by-code/{production_order_code}",
    response_model=ProductionOrderOut,
    summary="Get production order by business code",
)
def get_production_order_by_code(
    production_order_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_production_order_by_code(
        db, tenant, production_order_code
    )


@router.post(
    "/production-orders",
    response_model=ProductionOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create production order",
)
def create_production_order(
    payload: ProductionOrderCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_production_order(db, tenant, payload)


# --- Production lots ---


@router.get(
    "/production-lots",
    response_model=List[ProductionLotOut],
    summary="List production lots",
)
def list_production_lots(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_production_lots(db, tenant)


@router.get(
    "/production-lots/{production_lot_id}",
    response_model=ProductionLotOut,
    summary="Get production lot by ID",
)
def get_production_lot(
    production_lot_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_production_lot(db, tenant, production_lot_id)


@router.post(
    "/production-lots",
    response_model=ProductionLotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create production lot",
)
def create_production_lot(
    payload: ProductionLotCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_production_lot(db, tenant, payload)


@router.post(
    "/production-orders/{production_order_id}/split-lots",
    response_model=ProductionLotSplitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Split a production order into lots (sum must equal planned qty)",
)
def split_production_lots(
    production_order_id: UUID,
    payload: ProductionLotSplitRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.split_production_lots(
        db, tenant, production_order_id, payload
    )


# --- Feasibility checks ---


@router.get(
    "/feasibility-checks",
    response_model=List[FeasibilityCheckOut],
    summary="List feasibility checks",
)
def list_feasibility_checks(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_feasibility_checks(db, tenant)


@router.get(
    "/feasibility-checks/{feasibility_check_id}",
    response_model=FeasibilityCheckOut,
    summary="Get feasibility check by ID",
)
def get_feasibility_check(
    feasibility_check_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_feasibility_check(db, tenant, feasibility_check_id)


@router.post(
    "/feasibility-checks",
    response_model=FeasibilityCheckOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create feasibility check",
)
def create_feasibility_check(
    payload: FeasibilityCheckCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_feasibility_check(db, tenant, payload)


@router.get(
    "/production-lots/by-code/{lot_code}/feasibility",
    response_model=FeasibilityGateOut,
    summary="Latest feasibility gate for a lot (by lot code)",
)
def get_lot_feasibility(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_feasibility.get_feasibility_for_lot(db, tenant, lot_code)


@router.post(
    "/production-lots/by-code/{lot_code}/feasibility/run",
    response_model=FeasibilityResponse,
    summary="Run feasibility check for a lot and persist the result",
)
def run_lot_feasibility(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_feasibility.run_feasibility_check(db, tenant, lot_code)


# --- Scheduling ---


@router.get(
    "/schedules",
    response_model=List[ScheduleOut],
    summary="List production schedules",
)
def list_schedules(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_scheduling.list_schedules(db, tenant)


@router.post(
    "/schedules",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a production schedule for a lot operation",
)
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_scheduling.create_schedule(db, tenant, payload)


@router.get(
    "/production-lots/by-code/{lot_code}/schedule-plan",
    response_model=SchedulePlanOut,
    summary="Scheduling plan for a lot (routing operations + suggestions)",
)
def get_schedule_plan(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_scheduling.get_schedule_plan(db, tenant, lot_code)


@router.get(
    "/production-lots/by-code/{lot_code}/execution-summary",
    summary="Aggregate work-order state for a lot (execution screen)",
)
def get_lot_execution_summary(
    lot_code: str,
    sync: bool = False,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    summary = mes_core_execution.lot_execution_summary(
        db, tenant, lot_code, sync=sync
    )
    template = (tenant.industry_template_code or "").upper()
    if "ACTIVATED" in template or template == "ACTIVATED_CARBON":
        from app.services.industry.activated_carbon import (
            execution_enrich as ac_execution_enrich,
        )

        summary = ac_execution_enrich.enrich_lot_execution_summary(
            db, tenant, summary
        )
    return summary


@router.put(
    "/execution/by-code/{execution_code}/start",
    response_model=WorkOrderOut,
    summary="Start a scheduled operation (shop floor)",
)
def start_execution(
    execution_code: str,
    payload: WorkOrderStartRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    out = mes_core_execution.start_execution(db, tenant, execution_code, payload)
    template = (tenant.industry_template_code or "").upper()
    if "ACTIVATED" in template or template == "ACTIVATED_CARBON":
        from app.services.industry.activated_carbon import stock as ac_stock

        ac_stock.on_execution_started(db, tenant, execution_code)
    return out


@router.put(
    "/execution/by-code/{execution_code}/hold",
    response_model=WorkOrderOut,
    summary="Put an operation on hold",
)
def hold_execution(
    execution_code: str,
    payload: WorkOrderHoldRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_execution.hold_execution(db, tenant, execution_code, payload)


@router.put(
    "/execution/by-code/{execution_code}/resume",
    response_model=WorkOrderOut,
    summary="Resume an operation that was on hold",
)
def resume_execution(
    execution_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_execution.resume_execution(db, tenant, execution_code)


@router.put(
    "/execution/by-code/{execution_code}/complete",
    response_model=WorkOrderOut,
    summary="Complete an in-progress operation",
)
def complete_execution(
    execution_code: str,
    payload: WorkOrderCompleteRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    out = mes_core_execution.complete_execution(
        db, tenant, execution_code, payload
    )
    template = (tenant.industry_template_code or "").upper()
    if "ACTIVATED" in template or template == "ACTIVATED_CARBON":
        from app.services.industry.activated_carbon import stock as ac_stock

        ac_stock.after_work_order_completed(db, tenant, execution_code)
    return out


@router.post(
    "/execution/by-code/{execution_code}/parameter-readings",
    response_model=WorkOrderOut,
    summary="Append parameter readings to a completed operation",
)
def append_execution_parameter_readings(
    execution_code: str,
    payload: ParameterReadingsAppendRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_execution.append_execution_parameter_readings(
        db, tenant, execution_code, payload.parameter_readings
    )


# --- Execution (CRUD) ---


@router.get(
    "/execution",
    response_model=List[OperationExecutionOut],
    summary="List operation executions",
)
def list_executions(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_executions(db, tenant)


@router.get(
    "/execution/{execution_id}",
    response_model=OperationExecutionOut,
    summary="Get operation execution by ID",
)
def get_execution(
    execution_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_execution(db, tenant, execution_id)


@router.post(
    "/execution",
    response_model=OperationExecutionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create operation execution",
)
def create_execution(
    payload: OperationExecutionCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_execution(db, tenant, payload)


# --- Quality checks ---


@router.get(
    "/quality-checks",
    response_model=List[QualityCheckOut],
    summary="List quality checks",
)
def list_quality_checks(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_quality_checks(db, tenant)


@router.get(
    "/quality-checks/{quality_check_id}",
    response_model=QualityCheckOut,
    summary="Get quality check by ID",
)
def get_quality_check(
    quality_check_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_quality_check(db, tenant, quality_check_id)


@router.post(
    "/quality-checks",
    response_model=QualityCheckOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create quality check",
)
def create_quality_check(
    payload: QualityCheckCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_quality_check(db, tenant, payload)


# --- Inspection & NCR (legacy-compatible shapes) ---


@router.get(
    "/inspection-results",
    response_model=List[InspectionResultOut],
    summary="List lot inspection results",
)
def list_inspection_results(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_quality.list_inspection_results(db, tenant)


@router.post(
    "/inspection-results",
    response_model=InspectionResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a lot inspection result",
)
def create_inspection_result(
    payload: InspectionResultCreateRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    create_payload = InspectionResultCreate(
        inspection_id=payload.inspection_id,
        work_order_id=payload.work_order_id,
        lot_id=payload.lot_id,
        inspection_plan_id=payload.inspection_plan_id,
        inspected_quantity=payload.inspected_quantity,
        accepted_quantity=payload.accepted_quantity,
        rejected_quantity=payload.rejected_quantity,
        inspection_status=payload.inspection_status,
        inspected_at=payload.inspected_at,
    )
    params = [p.model_dump() for p in payload.parameters]
    return mes_core_quality.create_inspection_result(
        db, tenant, create_payload, parameters=params
    )


@router.get(
    "/ncrs",
    response_model=List[NCROut],
    summary="List non-conformance reports",
)
def list_ncrs(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_quality.list_ncrs(db, tenant)


@router.post(
    "/ncrs",
    response_model=NCROut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an NCR against a failed inspection",
)
def create_ncr(
    payload: NCRCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_quality.create_ncr(db, tenant, payload)


# --- Dispatch ---


@router.get(
    "/dispatches",
    response_model=List[DispatchOut],
    summary="List dispatches",
)
def list_dispatches(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_dispatch.list_dispatches(db, tenant)


@router.post(
    "/dispatches",
    response_model=DispatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dispatch (gate-checked per lot line)",
)
def create_dispatch(
    payload: DispatchCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_dispatch.create_dispatch(db, tenant, payload)


@router.get(
    "/production-lots/by-code/{lot_code}/traceability",
    response_model=TraceabilityResponse,
    summary="End-to-end traceability graph for a lot",
)
def get_lot_traceability(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_traceability.get_traceability(db, tenant, lot_code)


# --- Intelligence hub ---


@router.get(
    "/intelligence/hub",
    response_model=IntelligenceHubOut,
    summary="Operational intelligence hub KPIs and signals (mes_core)",
)
def get_intelligence_hub(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_intelligence.get_intelligence_hub(db, tenant)


@router.get(
    "/oee/intelligence",
    response_model=OEEIntelligenceResponse,
    summary="OEE intelligence dashboard payload (mes_core)",
)
def get_oee_intelligence(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_oee.get_oee_intelligence(db, tenant)


@router.post(
    "/oee/daily-summary",
    response_model=OEEDailySummaryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record or update a validated daily OEE summary for a machine",
)
def record_oee_daily_summary(
    payload: OEEDailySummaryCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_oee.record_oee_daily_summary(db, tenant, payload)


# --- Ask Nyra ---


@router.post(
    "/ask",
    response_model=AskNyraResponse,
    summary="Ask Nyra — rule-based reasoning over mes_core workflow data",
)
def ask_nyra(
    payload: AskNyraRequest,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_ask.ask_nyra(
        db,
        tenant,
        question=payload.question,
        lot_id=payload.lot_id,
    )


# --- KG triples ---


@router.get(
    "/kg/triples",
    response_model=List[TripleOut],
    summary="List staged KG triples",
)
def list_triples(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.list_triples(db, tenant)


@router.get(
    "/kg/triples/{triple_id}",
    response_model=TripleOut,
    summary="Get KG triple by ID",
)
def get_triple(
    triple_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.get_triple(db, tenant, triple_id)


@router.post(
    "/kg/triples",
    response_model=TripleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Stage a KG triple",
)
def create_triple(
    payload: TripleCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return mes_core_service.create_triple(db, tenant, payload)
