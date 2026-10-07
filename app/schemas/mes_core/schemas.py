"""Shared Pydantic schemas for nyra_mes_core ``/api/*`` responses."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MesCoreModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TenantContextOut(BaseModel):
    tenant_id: UUID
    tenant_code: str
    tenant_name: str
    workspace_id: Optional[UUID] = None
    workspace_code: Optional[str] = None
    workspace_name: Optional[str] = None
    industry_template_code: str
    industry_template_name: str
    module_code: Optional[str] = None
    landing_page: Optional[str] = None
    ui_module_name: Optional[str] = None
    api_module_name: Optional[str] = None
    icon_name: Optional[str] = None
    dashboard_component: Optional[str] = None
    enabled_capabilities: list[str] = Field(default_factory=list)
    demo_mode: bool = False
    demo_read_only: bool = False
    demo_watermark: Optional[str] = None


class IndustryTemplateOut(MesCoreModel):
    industry_template_id: UUID
    template_code: str
    template_name: str
    description: Optional[str] = None
    template_version: str
    is_active: bool
    module_code: Optional[str] = None
    landing_page: Optional[str] = None
    ui_module_name: Optional[str] = None
    api_module_name: Optional[str] = None
    icon_name: Optional[str] = None
    dashboard_component: Optional[str] = None
    display_order: int = 100


class IndustryTemplateMetadataOut(BaseModel):
    template_code: str
    template_name: str
    module_code: Optional[str] = None
    landing_page: Optional[str] = None
    ui_module_name: Optional[str] = None
    api_module_name: Optional[str] = None
    icon_name: Optional[str] = None
    dashboard_component: Optional[str] = None
    display_order: int = 100
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityOut(MesCoreModel):
    capability_id: UUID
    capability_code: str
    capability_name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool
    display_order: Optional[int] = None
    is_required: Optional[bool] = None


class ProjectWorkspaceOut(MesCoreModel):
    workspace_id: UUID
    tenant_id: UUID
    workspace_code: str
    workspace_name: str
    status: str


class ActivatedCarbonYieldSummaryOut(BaseModel):
    lot_count: int
    total_planned_quantity: Decimal
    total_lot_quantity: Decimal
    average_yield_pct: Optional[Decimal] = None
    industry_template_code: str


class CustomerOut(MesCoreModel):
    customer_id: UUID
    tenant_id: UUID
    customer_code: str
    customer_name: str
    status: str
    created_at: Optional[datetime] = None


class CustomerCreate(BaseModel):
    customer_code: Optional[str] = Field(None, max_length=64)
    customer_name: str = Field(..., min_length=1, max_length=256)
    status: str = "ACTIVE"


class SupplierOut(MesCoreModel):
    supplier_id: UUID
    tenant_id: UUID
    supplier_code: str
    supplier_name: str
    status: str
    created_at: Optional[datetime] = None


class SupplierCreate(BaseModel):
    supplier_code: Optional[str] = Field(None, max_length=64)
    supplier_name: str = Field(..., min_length=1, max_length=256)
    status: str = "ACTIVE"


class ProductOut(MesCoreModel):
    product_id: UUID
    tenant_id: UUID
    product_code: str
    product_name: str
    product_type: Optional[str] = None
    uom: str
    status: str
    created_at: Optional[datetime] = None


class ProductCreate(BaseModel):
    product_code: Optional[str] = Field(None, max_length=64)
    product_name: str = Field(..., min_length=1, max_length=256)
    product_type: Optional[str] = None
    uom: str = "EA"
    status: str = "ACTIVE"


class ResourceOut(MesCoreModel):
    resource_id: UUID
    tenant_id: UUID
    resource_code: str
    resource_name: str
    resource_type: str
    status: str
    station: Optional[str] = None
    unit_count: Optional[int] = None
    monthly_capacity_kg: Optional[int] = None
    headcount: Optional[int] = None
    created_at: Optional[datetime] = None


class ResourceCreate(BaseModel):
    resource_code: Optional[str] = Field(None, max_length=64)
    resource_name: str = Field(..., min_length=1, max_length=256)
    resource_type: str = Field(..., min_length=1, max_length=64)
    status: str = "ACTIVE"
    station: Optional[str] = Field(None, max_length=64)
    unit_count: Optional[int] = Field(None, ge=1)
    monthly_capacity_kg: Optional[int] = Field(None, ge=1)
    headcount: Optional[int] = Field(None, ge=1)


class ResourceUpdate(BaseModel):
    monthly_capacity_kg: Optional[int] = Field(None, ge=1)
    unit_count: Optional[int] = Field(None, ge=1)


class EquipmentOut(MesCoreModel):
    equipment_id: UUID
    tenant_id: UUID
    equipment_code: str
    equipment_name: str
    resource_id: Optional[UUID] = None
    equipment_type: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None


class EquipmentCreate(BaseModel):
    equipment_code: Optional[str] = Field(None, max_length=64)
    equipment_name: str = Field(..., min_length=1, max_length=256)
    resource_id: Optional[UUID] = None
    equipment_type: Optional[str] = None
    status: str = "ACTIVE"


class RoutingOperationOut(MesCoreModel):
    routing_operation_id: UUID
    tenant_id: UUID
    routing_id: UUID
    operation_code: str
    operation_sequence: int
    operation_name: str
    standard_cycle_min: Optional[Decimal] = None
    process_id: Optional[str] = None
    inspection_required: Optional[bool] = None


class RoutingOut(MesCoreModel):
    routing_id: UUID
    tenant_id: UUID
    routing_code: str
    product_id: Optional[UUID] = None
    routing_version: str
    process_family: Optional[str] = None
    is_active: bool
    operations: list[RoutingOperationOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class RoutingCreate(BaseModel):
    routing_code: Optional[str] = Field(None, max_length=64)
    product_id: UUID
    routing_version: str = "1"
    process_family: Optional[str] = None
    is_active: bool = True


class RoutingOperationCreate(BaseModel):
    operation_code: Optional[str] = Field(None, max_length=64)
    operation_sequence: int = Field(..., gt=0)
    operation_name: str = Field(..., min_length=1, max_length=256)
    process_id: Optional[str] = None
    process_code: Optional[str] = None
    process_name: Optional[str] = None
    process_type: Optional[str] = None
    standard_cycle_time_minutes: Optional[Decimal] = None
    inspection_required: bool = False


class RoutingWithOperationsCreate(BaseModel):
    routing_code: Optional[str] = Field(None, max_length=64)
    product_id: UUID
    routing_version: str = "1"
    process_family: Optional[str] = None
    is_active: bool = True
    operations: list[RoutingOperationCreate] = Field(..., min_length=1)


class RoutingWithOperationsOut(BaseModel):
    routing: RoutingOut
    operations: list[RoutingOperationOut]


class CopyRoutingFromTemplateRequest(BaseModel):
    template_routing_code: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Industry template routing code (e.g. AC_STANDARD_PROCESS)",
    )


class OperationResourceRequirementOut(MesCoreModel):
    requirement_id: UUID
    routing_operation_id: UUID
    resource_id: UUID
    resource_code: str
    resource_name: str
    resource_type: str
    requirement_type: str
    quantity: Decimal = Decimal("1")
    uom: str = "EA"


class OperationResourceRequirementCreate(BaseModel):
    resource_id: UUID
    requirement_type: str = Field(..., min_length=1, max_length=32)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    uom: str = Field(default="EA", max_length=16)


class OperationResourceRequirementsSet(BaseModel):
    requirements: list[OperationResourceRequirementCreate] = Field(default_factory=list)


class RoutingOperationDetailOut(MesCoreModel):
    routing_operation_id: UUID
    tenant_id: UUID
    workspace_id: Optional[UUID] = None
    routing_id: UUID
    operation_code: str
    operation_sequence: int
    operation_seq: int
    operation_name: str
    operation_type: Optional[str] = None
    standard_cycle_min: Optional[Decimal] = None
    is_quality_gate: bool = False
    is_feasibility_gate: bool = False
    is_active: bool = True
    is_customized: bool = False
    source_template_operation_code: Optional[str] = None
    process_id: Optional[str] = None
    resource_requirements: list[OperationResourceRequirementOut] = Field(
        default_factory=list
    )
    parameters: list["RoutingOperationParameterOut"] = Field(default_factory=list)


class ActiveRoutingOut(MesCoreModel):
    routing_id: UUID
    tenant_id: UUID
    workspace_id: Optional[UUID] = None
    routing_code: str
    product_id: Optional[UUID] = None
    routing_version: str
    process_family: Optional[str] = None
    is_active: bool
    industry_template_code: Optional[str] = None
    source_template_code: Optional[str] = None
    is_template_route: bool = False
    is_template_copy: bool = False
    is_customized: bool = False
    operations: list[RoutingOperationDetailOut] = Field(default_factory=list)


class RoutingOperationCreateRequest(BaseModel):
    operation_code: Optional[str] = Field(None, max_length=64)
    operation_seq: Optional[int] = Field(None, gt=0)
    operation_sequence: Optional[int] = Field(None, gt=0)
    operation_name: str = Field(..., min_length=1, max_length=256)
    operation_type: Optional[str] = Field(None, max_length=64)
    process_step: Optional[str] = Field(None, max_length=64)
    standard_cycle_min: Optional[Decimal] = None
    is_quality_gate: bool = False
    is_feasibility_gate: bool = False


class RoutingOperationSequencePatch(BaseModel):
    operation_seq: int = Field(..., gt=0)


class RoutingOperationUpdateRequest(BaseModel):
    operation_name: Optional[str] = Field(None, min_length=1, max_length=256)
    operation_type: Optional[str] = Field(None, max_length=64)
    is_quality_gate: Optional[bool] = None
    is_feasibility_gate: Optional[bool] = None
    is_active: Optional[bool] = None
    standard_cycle_min: Optional[Decimal] = None


class RoutingOperationParameterCreate(BaseModel):
    parameter_code: str = Field(..., min_length=1, max_length=64)
    parameter_name: str = Field(..., min_length=1, max_length=256)
    data_type: Optional[str] = Field(None, max_length=32)
    unit: Optional[str] = Field(None, max_length=32)
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    is_mandatory: bool = False
    reading_frequency: Optional[str] = Field(None, max_length=64)
    display_order: Optional[int] = None


class RoutingOperationParameterUpdate(BaseModel):
    parameter_name: Optional[str] = Field(None, min_length=1, max_length=256)
    data_type: Optional[str] = Field(None, max_length=32)
    unit: Optional[str] = Field(None, max_length=32)
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    is_mandatory: Optional[bool] = None
    reading_frequency: Optional[str] = Field(None, max_length=64)
    display_order: Optional[int] = None


class RoutingOperationParameterOut(MesCoreModel):
    id: UUID
    tenant_id: UUID
    workspace_id: Optional[UUID] = None
    routing_operation_id: UUID
    parameter_code: Optional[str] = None
    parameter_name: Optional[str] = None
    data_type: Optional[str] = None
    unit: Optional[str] = None
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    is_mandatory: bool = False
    reading_frequency: Optional[str] = None
    display_order: Optional[int] = None
    is_active: bool = True
    created_at: Optional[datetime] = None


class TrnDispatchCreate(BaseModel):
    customer_order_id: Optional[UUID] = None
    production_lot_id: Optional[UUID] = None
    finished_goods_lot_no: Optional[str] = Field(None, max_length=128)
    grade: Optional[str] = Field(None, max_length=64)
    bag_count: Optional[Decimal] = None
    total_weight: Optional[Decimal] = None
    vehicle_no: Optional[str] = Field(None, max_length=64)
    dispatch_date: Optional[date] = None
    invoice_ref: Optional[str] = Field(None, max_length=128)
    destination: Optional[str] = None
    status: str = Field(default="PLANNED", max_length=32)


class TrnDispatchUpdate(BaseModel):
    customer_order_id: Optional[UUID] = None
    production_lot_id: Optional[UUID] = None
    finished_goods_lot_no: Optional[str] = Field(None, max_length=128)
    grade: Optional[str] = Field(None, max_length=64)
    bag_count: Optional[Decimal] = None
    total_weight: Optional[Decimal] = None
    vehicle_no: Optional[str] = Field(None, max_length=64)
    dispatch_date: Optional[date] = None
    invoice_ref: Optional[str] = Field(None, max_length=128)
    destination: Optional[str] = None
    status: Optional[str] = Field(None, max_length=32)


class TrnDispatchOut(MesCoreModel):
    id: UUID
    tenant_id: UUID
    workspace_id: Optional[UUID] = None
    customer_order_id: Optional[UUID] = None
    production_lot_id: Optional[UUID] = None
    finished_goods_lot_no: Optional[str] = None
    grade: Optional[str] = None
    bag_count: Optional[Decimal] = None
    total_weight: Optional[Decimal] = None
    vehicle_no: Optional[str] = None
    dispatch_date: Optional[date] = None
    invoice_ref: Optional[str] = None
    destination: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CustomerOrderLineOut(MesCoreModel):
    order_line_id: UUID
    tenant_id: UUID
    order_id: UUID
    line_code: str
    product_id: UUID
    product_code: Optional[str] = None
    quantity: Decimal
    uom: str
    status: str
    created_at: Optional[datetime] = None


class CustomerOrderOut(MesCoreModel):
    customer_order_id: UUID
    tenant_id: UUID
    order_code: str
    customer_id: Optional[UUID] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    supplier_id: Optional[UUID] = None
    supplier_code: Optional[str] = None
    supplier_name: Optional[str] = None
    order_date: Optional[date] = None
    delivery_date: Optional[date] = None
    status: str
    lines: list[CustomerOrderLineOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    # Activated carbon raw-material inward enrichment (list_raw_material_inward)
    raw_product_code: Optional[str] = None
    inward_quantity_kg: Optional[Decimal] = None
    allocated_to_production_kg: Optional[Decimal] = None
    available_quantity_kg: Optional[Decimal] = None
    qc_status: Optional[str] = None
    dc_number: Optional[str] = None
    supplier_weight_kg: Optional[Decimal] = None
    our_weight_kg: Optional[Decimal] = None
    supplier_value_inr: Optional[Decimal] = None
    lab_status: Optional[str] = None
    lab_at: Optional[datetime] = None
    rms_inward_status: Optional[str] = None
    rms_inward_at: Optional[datetime] = None
    rm_outward_status: Optional[str] = None
    rm_outward_at: Optional[datetime] = None
    released_to_production_status: Optional[str] = None
    released_to_production_at: Optional[datetime] = None


class CustomerOrderLineCreate(BaseModel):
    line_code: Optional[str] = Field(None, max_length=64)
    product_id: UUID
    quantity: Decimal = Field(..., gt=0)
    uom: str = "EA"
    status: str = "OPEN"


class CustomerOrderCreate(BaseModel):
    order_code: Optional[str] = Field(None, max_length=64)
    customer_id: Optional[UUID] = None
    supplier_id: Optional[UUID] = None
    status: str = "OPEN"
    delivery_date: Optional[date] = None
    line: CustomerOrderLineCreate


class InwardOrderCreate(BaseModel):
    """Raw material inward — supplier-scoped order (no end customer)."""

    order_code: Optional[str] = Field(None, max_length=64)
    supplier_id: UUID
    status: str = "OPEN"
    line: CustomerOrderLineCreate


class CustomerOrderCreateResponse(BaseModel):
    order: CustomerOrderOut
    line: CustomerOrderLineOut


class ProductionOrderOut(MesCoreModel):
    production_order_id: UUID
    tenant_id: UUID
    production_order_code: str
    order_line_id: UUID
    order_line_code: Optional[str] = None
    product_code: Optional[str] = None
    planned_quantity: Decimal
    status: str
    created_at: Optional[datetime] = None


class ProductionOrderCreate(BaseModel):
    production_order_code: Optional[str] = Field(None, max_length=64)
    order_line_id: UUID
    planned_quantity: Decimal = Field(..., gt=0)
    status: str = "PLANNED"


class ProductionLotOut(MesCoreModel):
    production_lot_id: UUID
    tenant_id: UUID
    lot_code: str
    production_order_id: UUID
    production_order_code: Optional[str] = None
    lot_quantity: Decimal
    status: str
    created_at: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None
    kiln_resource_code: Optional[str] = None
    charged_at: Optional[str] = None
    crusher_grade: Optional[str] = None
    crusher_bag_code: Optional[str] = None
    crusher_outward_bags: list[Any] = Field(default_factory=list)
    kiln_feed_events: list[Any] = Field(default_factory=list)
    kiln_loaded_kg: Optional[Decimal] = None


class ProductionLotSplitItem(BaseModel):
    lot_quantity: Decimal = Field(..., gt=0)
    status: str = "CREATED"


class ProductionLotSplitRequest(BaseModel):
    lots: list[ProductionLotSplitItem] = Field(..., min_length=1)


class ProductionLotSplitResponse(BaseModel):
    production_order: ProductionOrderOut
    lots: list[ProductionLotOut]


class ProductionLotCreate(BaseModel):
    lot_code: Optional[str] = Field(None, max_length=64)
    production_order_id: UUID
    lot_quantity: Decimal = Field(..., gt=0)
    status: str = "CREATED"


class FeasibilityCheckOut(MesCoreModel):
    feasibility_check_id: UUID
    tenant_id: UUID
    check_code: str
    production_lot_id: UUID
    overall_status: str
    checked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class FeasibilityCheckCreate(BaseModel):
    check_code: Optional[str] = Field(None, max_length=64)
    production_lot_id: UUID
    overall_status: str = "PENDING"


class OperationExecutionOut(MesCoreModel):
    execution_id: UUID
    tenant_id: UUID
    execution_code: str
    production_lot_id: UUID
    routing_operation_id: UUID
    equipment_id: Optional[UUID] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class OperationExecutionCreate(BaseModel):
    execution_code: Optional[str] = Field(None, max_length=64)
    production_lot_id: UUID
    routing_operation_id: UUID
    equipment_id: Optional[UUID] = None
    status: str = "NOT_STARTED"


class ScheduleCreate(BaseModel):
    schedule_id: Optional[str] = Field(None, max_length=64)
    lot_id: str
    operation_id: Optional[str] = None
    planned_start_time: Optional[datetime] = None
    planned_end_time: Optional[datetime] = None
    assigned_work_center_id: Optional[str] = None
    assigned_machine_id: Optional[str] = None
    schedule_status: Optional[str] = "Scheduled"


class ScheduleOut(MesCoreModel):
    schedule_id: str
    lot_id: Optional[str] = None
    operation_id: Optional[str] = None
    planned_start_time: Optional[datetime] = None
    planned_end_time: Optional[datetime] = None
    assigned_work_center_id: Optional[str] = None
    assigned_machine_id: Optional[str] = None
    schedule_status: Optional[str] = None
    created_at: Optional[datetime] = None


class SchedulePlanOperationOut(BaseModel):
    operation_id: str
    operation_sequence: int
    operation_name: str
    standard_cycle_time_minutes: Optional[float] = None
    estimated_duration_minutes: Optional[float] = None
    inspection_required: bool = False
    suggested_machine_id: Optional[str] = None
    suggested_machine_name: Optional[str] = None
    suggested_work_center_id: Optional[str] = None
    suggested_work_center_name: Optional[str] = None
    existing_schedule_id: Optional[str] = None
    already_scheduled: bool = False


class SchedulePlanOut(BaseModel):
    lot_id: str
    lot_quantity: float
    lot_status: str
    production_order_id: Optional[str] = None
    part_id: Optional[str] = None
    part_name: Optional[str] = None
    routing_id: Optional[str] = None
    routing_version: Optional[str] = None
    operations: list[SchedulePlanOperationOut] = Field(default_factory=list)


class FeasibilityGateOut(BaseModel):
    lot_id: str
    overall_status: str
    material_status: Optional[str] = None
    machine_status: Optional[str] = None
    tool_status: Optional[str] = None
    workforce_status: Optional[str] = None
    blocked_reason: Optional[str] = None
    checked_at: Optional[datetime] = None


class QualityCheckOut(MesCoreModel):
    quality_check_id: UUID
    tenant_id: UUID
    check_code: str
    production_lot_id: UUID
    check_type: str
    status: str
    created_at: Optional[datetime] = None


class QualityCheckCreate(BaseModel):
    check_code: Optional[str] = Field(None, max_length=64)
    production_lot_id: UUID
    check_type: str = "IN_PROCESS"
    status: str = "OPEN"


class InspectionParameterInput(BaseModel):
    name: str = ""
    observed: str = ""
    spec: str = ""


class InspectionResultCreateRequest(BaseModel):
    inspection_id: Optional[str] = Field(None, max_length=64)
    work_order_id: Optional[str] = None
    lot_id: Optional[str] = None
    inspection_plan_id: Optional[str] = None
    inspected_quantity: Optional[Decimal] = None
    accepted_quantity: Optional[Decimal] = None
    rejected_quantity: Optional[Decimal] = None
    inspection_status: Optional[str] = "Pending"
    inspected_at: Optional[datetime] = None
    parameters: list[InspectionParameterInput] = Field(default_factory=list)


class TripleOut(MesCoreModel):
    triple_id: UUID
    tenant_id: UUID
    subject_uri: str
    predicate_uri: str
    object_uri: Optional[str] = None
    object_literal: Optional[str] = None
    object_datatype: Optional[str] = None
    source_table: Optional[str] = None
    source_id: Optional[UUID] = None
    export_status: str
    created_at: Optional[datetime] = None


class TripleCreate(BaseModel):
    subject_uri: str
    predicate_uri: str
    object_uri: Optional[str] = None
    object_literal: Optional[str] = None
    object_datatype: Optional[str] = None
    source_table: Optional[str] = None
    source_id: Optional[UUID] = None
    export_status: str = "PENDING"
    metadata: Optional[dict[str, Any]] = None


class AskNyraRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    lot_id: Optional[str] = Field(None, max_length=64)


class AskNyraResponse(BaseModel):
    question: str
    lot_id: Optional[str] = None
    answer: str
    sources: list[str] = Field(default_factory=list)


class IntelligenceHubKpisOut(BaseModel):
    production_orders: int = 0
    work_orders: int = 0
    ncr_count: int = 0
    open_ncrs: int = 0
    dispatch_count: int = 0
    average_oee: float = 0


class IntelligenceHubOut(BaseModel):
    kpis: IntelligenceHubKpisOut
    orders: list[dict[str, Any]] = Field(default_factory=list)
    lots: list[dict[str, Any]] = Field(default_factory=list)
    order_lot_lines: list[dict[str, Any]] = Field(default_factory=list)
    oee_trend: list[dict[str, Any]] = Field(default_factory=list)
    oee_summaries: list[dict[str, Any]] = Field(default_factory=list)
    plant_kpis: dict[str, Any] = Field(default_factory=dict)
    open_work_orders: list[dict[str, Any]] = Field(default_factory=list)
    open_ncrs: list[dict[str, Any]] = Field(default_factory=list)
    dispatches: list[dict[str, Any]] = Field(default_factory=list)


# --- Activated Carbon data-entry payloads ---


class AcKilnParameterDefinition(BaseModel):
    key: str
    label: str
    unit: Optional[str] = None


class AcKilnParameterDefinitionCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    unit: Optional[str] = Field(None, max_length=32)


class AcKilnCreate(BaseModel):
    kiln_name: str = Field(..., min_length=1, max_length=256)
    resource_code: Optional[str] = Field(None, max_length=64)
    equipment_code: Optional[str] = Field(None, max_length=64)
    status: str = "ACTIVE"
    monthly_capacity_kg: Optional[int] = Field(None, ge=1)


class AcKilnOut(BaseModel):
    resource_id: UUID
    resource_code: str
    resource_name: str
    equipment_id: UUID
    equipment_code: str
    equipment_name: str
    status: str
    monthly_capacity_kg: Optional[int] = None


class AcPlantResourceOut(BaseModel):
    resource_id: UUID
    resource_code: str
    resource_name: str
    resource_type: str
    status: str
    station: Optional[str] = None
    unit_count: Optional[int] = None
    monthly_capacity_kg: Optional[int] = None
    headcount: Optional[int] = None
    equipment_id: Optional[UUID] = None
    equipment_code: Optional[str] = None
    equipment_name: Optional[str] = None


class AcRoutingOperationSummary(BaseModel):
    operation_code: str
    operation_sequence: int
    operation_name: str
    process_step: Optional[str] = None


class AcRoutingMasterOut(BaseModel):
    routing_code: str
    routing_version: Optional[str] = None
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    operations: list[AcRoutingOperationSummary] = Field(default_factory=list)
    seed_script: str = "scripts/db/nyra_sam_carbons_demo_tenant.sql"


class AcMastersOut(BaseModel):
    customers: list[CustomerOut] = Field(default_factory=list)
    raw_products: list[ProductOut] = Field(default_factory=list)
    raw_material_types: list["AcRawMaterialTypeOut"] = Field(default_factory=list)
    finished_products: list[ProductOut] = Field(default_factory=list)
    production_orders: list[ProductionOrderOut] = Field(default_factory=list)
    production_lots: list[ProductionLotOut] = Field(default_factory=list)
    kilns: list[ResourceOut] = Field(default_factory=list)
    machines: list[ResourceOut] = Field(default_factory=list)
    tools: list[ResourceOut] = Field(default_factory=list)
    labor_pools: list[ResourceOut] = Field(default_factory=list)
    equipment: list[EquipmentOut] = Field(default_factory=list)
    kiln_parameter_definitions: list[AcKilnParameterDefinition] = Field(default_factory=list)
    routing_master: Optional[AcRoutingMasterOut] = None


class AcRawMaterialInwardCreate(BaseModel):
    supplier_id: UUID
    product_id: UUID
    quantity: Decimal = Field(..., gt=0)
    uom: str = "KG"
    dc_number: Optional[str] = Field(
        None,
        max_length=64,
        description="Supplier delivery challan (DC) number at inward receipt.",
    )
    supplier_weight_kg: Optional[Decimal] = Field(
        None,
        gt=0,
        description="Weight declared by supplier on DC (kg).",
    )
    our_weight_kg: Optional[Decimal] = Field(
        None,
        gt=0,
        description="Plant-weighed quantity at gate (kg). Used as received quantity when set.",
    )
    supplier_value_inr: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Supplier invoice / declared value in INR.",
    )
    our_value_inr: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Internal assessed value in INR at gate receipt.",
    )
    order_code: Optional[str] = Field(None, max_length=64)
    production_order_code: Optional[str] = Field(
        None,
        max_length=64,
        description="Optional fixed PO code (e.g. PO-AC-1001 for demo seed).",
    )
    create_production_order: bool = Field(
        default=False,
        description="When true, creates a production order at inward time. Prefer false — PO is created on release to production.",
    )


class AcRawMaterialInwardCreateResponse(BaseModel):
    order: CustomerOrderOut
    line: CustomerOrderLineOut
    production_order: Optional[ProductionOrderOut] = None


class AcRawMaterialQcOut(BaseModel):
    customer_order_id: UUID
    order_code: str
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[Decimal] = None
    uom: Optional[str] = None
    our_weight_kg: Optional[Decimal] = None
    moisture_pct: Optional[Decimal] = None
    ash_pct: Optional[Decimal] = None
    foreign_matter_pct: Optional[Decimal] = None
    stones_kg: Optional[Decimal] = None
    unburnt_kg: Optional[Decimal] = None
    minus20_kg: Optional[Decimal] = None
    operator_remarks: Optional[str] = None
    qc_status: str = "PENDING"
    qc_at: Optional[datetime] = None
    crush_status: str = "PENDING"
    crush_at: Optional[datetime] = None
    raw_material_type_id: Optional[UUID] = None
    inbound_steps: list["AcInboundStepStatusOut"] = Field(default_factory=list)
    inbound_prep_complete: bool = False
    next_inbound_step: Optional[str] = None
    next_inbound_operation_code: Optional[str] = None
    lab_denied: bool = False
    lab_remarks: Optional[str] = None


class AcInboundStepStatusOut(BaseModel):
    process_step: str
    operation_name: str
    operation_code: Optional[str] = None
    is_mandatory: bool = True
    status: str = "PENDING"
    completed_at: Optional[datetime] = None


class AcInboundStepCompleteCreate(BaseModel):
    customer_order_id: UUID
    process_step: str = Field(..., min_length=1, max_length=64)
    operation_code: Optional[str] = Field(
        None,
        max_length=64,
        description="Inbound prep operation code (required when multiple steps share a process_step).",
    )
    parameters: dict = Field(default_factory=dict)


class AcInboundExecutionOut(AcRawMaterialQcOut):
    """Inward order with configurable inbound prep step status."""


class AcRawMaterialCrushCreate(BaseModel):
    customer_order_id: UUID
    input_lump_size_mm: Optional[Decimal] = Field(None, ge=0)
    target_output_size_mm: Optional[Decimal] = Field(None, ge=0)
    throughput_kg_h: Optional[Decimal] = Field(None, ge=0)
    crush_output_kg: Decimal = Field(..., gt=0)
    crush_yield_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    moisture_before_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    moisture_after_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    dust_generation_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    crusher_id: Optional[str] = Field(None, max_length=64)
    operator_remarks: Optional[str] = None


class AcRawMaterialCrushOut(AcRawMaterialQcOut):
    """Same inward row shape as QC list, with crushing fields from order metadata."""


class AcRawMaterialQcCreate(BaseModel):
    customer_order_id: UUID
    moisture_pct: Optional[Decimal] = None
    ash_pct: Optional[Decimal] = None
    foreign_matter_pct: Optional[Decimal] = None
    stones_kg: Optional[Decimal] = Field(None, ge=0)
    unburnt_kg: Optional[Decimal] = Field(None, ge=0)
    minus20_kg: Optional[Decimal] = Field(None, ge=0)
    operator_remarks: Optional[str] = None
    qc_status: str = Field(default="PASS", max_length=32)


class AcInitialQcCreate(BaseModel):
    customer_order_id: UUID
    moisture_pct: Decimal = Field(..., ge=0, le=100, description="Moisture content (%)")
    dust_pct: Decimal = Field(..., ge=0, le=100, description="Dust content (%)")
    ad_value: Decimal = Field(..., ge=0, description="Apparent density / AD lab reading (not KG)")
    qc_status: str = Field(default="PASS", max_length=32)


class AcInboundWorkflowOut(BaseModel):
    customer_order_id: UUID
    order_code: str
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    quantity: Optional[Decimal] = None
    uom: Optional[str] = None
    initial_qc_status: str = "PENDING"
    initial_qc_at: Optional[str] = None
    moisture_pct: Optional[Decimal] = Field(None, description="Initial QC moisture (%)")
    dust_pct: Optional[Decimal] = Field(None, description="Initial QC dust (%)")
    ad_value: Optional[Decimal] = Field(None, description="Initial QC AD lab reading")
    received_kg: Optional[Decimal] = None
    supplier_weight_kg: Optional[Decimal] = None
    weight_to_crusher_kg: Optional[Decimal] = None
    weight_reconciled: bool = False
    variance_comment: Optional[str] = None
    bag_count: int = 0
    bags_total_kg: Optional[Decimal] = None
    bags_reconciled: bool = False
    bag_variance_comment: Optional[str] = None
    crusher_complete: bool = False
    crusher_at: Optional[str] = None
    rotary: Optional[str] = None
    crusher_grades: list["AcCrusherGradeOut"] = Field(default_factory=list)
    crusher_scrap: list["AcCrusherGradeOut"] = Field(default_factory=list)
    scrap_total_kg: Optional[Decimal] = None
    remaining_kg: Optional[Decimal] = None
    separation_complete: bool = False


class AcCrusherGradeOut(BaseModel):
    grade_label: str
    parameter_key: str
    quantity_kg: Decimal = Field(default=Decimal("0"))


class AcInitialQcOut(AcInboundWorkflowOut):
    pass


class AcCrusherOutputOut(AcInboundWorkflowOut):
    pass


class AcInwardBagCreate(BaseModel):
    customer_order_id: UUID
    grade: Optional[str] = Field(None, max_length=128)
    rotary: Optional[str] = Field(None, max_length=64)
    weight_kg: Decimal = Field(..., gt=0)
    label: Optional[str] = Field(None, max_length=128)


class AcInwardBagOut(BaseModel):
    bag_id: UUID
    bag_code: str
    customer_order_id: UUID
    order_code: str
    grade: Optional[str] = None
    rotary: Optional[str] = None
    weight_kg: Decimal
    label: Optional[str] = None
    status: str = "REGISTERED"
    created_at: Optional[str] = None
    fed_at: Optional[str] = None
    created_by: Optional[str] = None
    kiln_feed_qc: Optional[dict[str, Any]] = None


class AcInwardBagReconcileCreate(BaseModel):
    customer_order_id: UUID
    variance_comment: Optional[str] = Field(None, max_length=2000)


class AcInwardGradeSplitRow(BaseModel):
    grade_label: str = Field(..., min_length=1, max_length=128)
    quantity_kg: Decimal = Field(..., gt=0)


class AcInwardGradeSeparationCreate(BaseModel):
    customer_order_id: UUID
    grade_splits: list[AcInwardGradeSplitRow] = Field(..., min_length=1)


class AcWeightToCrusherCreate(BaseModel):
    customer_order_id: UUID
    weight_to_crusher_kg: Decimal = Field(..., gt=0)
    variance_comment: Optional[str] = Field(None, max_length=2000)


class AcInboundAdminRotary(BaseModel):
    code: str = Field("", max_length=64)
    name: str = Field(..., min_length=1, max_length=128)


class AcInboundAdminSplit(BaseModel):
    key: str = Field("", max_length=64)
    label: str = Field(..., min_length=1, max_length=128)


class AcInboundAdminOut(BaseModel):
    rotaries: list[AcInboundAdminRotary] = Field(default_factory=list)
    outward_splits: list[AcInboundAdminSplit] = Field(default_factory=list)


class AcInboundAdminUpdate(BaseModel):
    rotaries: list[AcInboundAdminRotary] = Field(default_factory=list)
    outward_splits: list[AcInboundAdminSplit] = Field(default_factory=list)


class AcIsa95UtilizationRagOut(BaseModel):
    """ISA-95 L3 machine utilization bands (% of monthly designed output)."""

    green_min_pct: int = 90
    amber_min_pct: int = 70
    red_below_pct: int = 70


class AcIsa95UtilizationRagUpdate(BaseModel):
    green_min_pct: int = Field(..., ge=0, le=100)
    amber_min_pct: int = Field(..., ge=0, le=100)
    red_below_pct: int = Field(..., ge=0, le=100)


class AcInwardBagFeedCreate(BaseModel):
    customer_order_id: UUID
    bag_id: UUID


class AcCrusherOutputCreate(BaseModel):
    customer_order_id: UUID
    rotary: str = Field(..., min_length=1, max_length=64)
    crusher_grade: Optional[str] = Field(None, max_length=128)
    mesh_plus_2_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh +2 weight (KG)")
    mesh_2_3_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh 2/3 weight (KG)")
    mesh_3_4_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh 3/4 weight (KG)")
    mesh_4_6_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh 4/6 weight (KG)")
    mesh_6_10_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh 6/10 weight (KG)")
    mesh_10_12_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh 10/12 weight (KG)")
    mesh_12_14_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh 12/14 weight (KG)")
    mesh_minus_14_kg: Optional[Decimal] = Field(None, ge=0, description="Scrap mesh -14 weight (KG)")
    mesh_plus_2_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh +2 share (%)")
    mesh_2_3_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh 2/3 share (%)")
    mesh_3_4_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh 3/4 share (%)")
    mesh_4_6_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh 4/6 share (%)")
    mesh_6_10_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh 6/10 share (%)")
    mesh_10_12_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh 10/12 share (%)")
    mesh_12_14_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh 12/14 share (%)")
    mesh_minus_14_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Mesh -14 share (%)")
    moisture_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Moisture after crush (%)")
    dust_pct: Optional[Decimal] = Field(None, ge=0, le=100, description="Dust / fines (%)")


class AcKilnFeedLotCreate(BaseModel):
    production_order_id: Optional[UUID] = None
    production_lot_id: Optional[UUID] = None
    lot_quantity: Optional[Decimal] = Field(None, gt=0)
    lot_code: Optional[str] = Field(None, max_length=64)
    kiln_resource_code: Optional[str] = Field(None, max_length=64)
    bag_code: Optional[str] = Field(None, max_length=64)
    quantity_kg: Optional[Decimal] = Field(None, gt=0)
    status: str = "IN_PROGRESS"


class AcKilnOutputBagCreate(BaseModel):
    kiln_resource_code: str = Field(..., max_length=64)
    quantity_kg: Decimal = Field(..., gt=0)
    lot_code: Optional[str] = Field(None, max_length=64)


class AcKilnOutputBagOut(BaseModel):
    bag_code: str
    quantity_kg: Decimal
    kiln_resource_code: str
    lot_code: Optional[str] = None
    created_at: Optional[str] = None


class AcKilnOutputListOut(BaseModel):
    kiln_resource_code: str
    bags: list[AcKilnOutputBagOut] = Field(default_factory=list)
    bag_count: int = 0
    total_kg: Decimal = Decimal("0")


class AcKilnFeedBagQcCreate(BaseModel):
    bag_code: str = Field(..., min_length=1, max_length=128)
    customer_order_id: Optional[UUID] = None
    values: dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = Field(None, max_length=128)
    lot_code: Optional[str] = Field(None, max_length=64)


class AcKilnFeedBagQcOut(BaseModel):
    bag_code: str
    customer_order_id: UUID
    order_code: str
    weight_kg: Decimal
    grade: Optional[str] = None
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    values: dict[str, Any] = Field(default_factory=dict)
    saved_at: Optional[str] = None


class AcKilnOutputBagQcCreate(BaseModel):
    bag_code: str = Field(..., min_length=1, max_length=128)
    kiln_resource_code: Optional[str] = Field(None, max_length=64)
    values: dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = Field(None, max_length=128)
    lot_code: Optional[str] = Field(None, max_length=64)


class AcKilnOutputBagQcOut(BaseModel):
    bag_code: str
    kiln_resource_code: str
    quantity_kg: Decimal
    lot_code: Optional[str] = None
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    values: dict[str, Any] = Field(default_factory=dict)
    saved_at: Optional[str] = None


class AcDestoningBagOut(BaseModel):
    bag_code: str
    quantity_kg: Decimal
    kiln_resource_code: Optional[str] = None
    lot_code: Optional[str] = None
    created_at: Optional[str] = None
    input_bag_codes: list[str] = Field(default_factory=list)


class AcDestoningKilnGroupOut(BaseModel):
    kiln_resource_code: str
    kiln_name: str
    bags: list[AcDestoningBagOut] = Field(default_factory=list)


class AcDestoningLoadEventOut(BaseModel):
    bag_code: Optional[str] = None
    lot_code: Optional[str] = None
    kg: Decimal = Decimal("0")
    loaded_at: Optional[str] = None
    kiln_resource_code: Optional[str] = None


class AcDestoningStateOut(BaseModel):
    kilns: list[AcDestoningKilnGroupOut] = Field(default_factory=list)
    loaded: list[AcDestoningBagOut] = Field(default_factory=list)
    loaded_kg: Decimal = Decimal("0")
    loader_count: int = 0
    loader_capacity: int = 6
    output_bags: list[AcDestoningBagOut] = Field(default_factory=list)
    load_events: list[AcDestoningLoadEventOut] = Field(default_factory=list)


class AcDestoningLoadCreate(BaseModel):
    bag_code: str = Field(..., min_length=1, max_length=128)


class AcDestoningOutputCreate(BaseModel):
    quantity_kg: Decimal = Field(..., gt=0)
    lot_code: Optional[str] = Field(None, max_length=64)
    bag_code: Optional[str] = Field(None, max_length=128)


class AcDestoningBagQcCreate(BaseModel):
    bag_code: str = Field(..., min_length=1, max_length=128)
    values: dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = Field(None, max_length=128)
    copy_from_bag_code: Optional[str] = Field(None, max_length=128)


class AcDestoningBagQcOut(BaseModel):
    bag_code: str
    quantity_kg: Decimal
    lot_code: Optional[str] = None
    created_at: Optional[str] = None
    user_id: Optional[str] = None
    input_bag_codes: list[str] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
    saved_at: Optional[str] = None


class AcPostActivationBagOut(BaseModel):
    bag_code: str
    quantity_kg: Decimal
    grade: Optional[str] = None
    lot_code: Optional[str] = None
    created_at: Optional[str] = None
    loaded_at: Optional[str] = None
    input_bag_codes: list[str] = Field(default_factory=list)
    process: Optional[str] = None


class AcPostActivationLoadEventOut(BaseModel):
    bag_code: Optional[str] = None
    lot_code: Optional[str] = None
    kg: Decimal = Decimal("0")
    loaded_at: Optional[str] = None
    process: Optional[str] = None


class AcPostActivationStateOut(BaseModel):
    process: str
    process_label: str
    available: list[AcPostActivationBagOut] = Field(default_factory=list)
    loaded: list[AcPostActivationBagOut] = Field(default_factory=list)
    loaded_kg: Decimal = Decimal("0")
    loader_count: int = 0
    loader_capacity: int = 6
    monthly_capacity_kg: int = 15000
    output_bags: list[AcPostActivationBagOut] = Field(default_factory=list)
    load_events: list[AcPostActivationLoadEventOut] = Field(default_factory=list)


class AcPostActivationLoadCreate(BaseModel):
    bag_code: str = Field(..., min_length=1, max_length=128)


class AcPostActivationOutputCreate(BaseModel):
    quantity_kg: Decimal = Field(..., gt=0)
    grade: str = Field(..., min_length=1, max_length=128)
    lot_code: Optional[str] = Field(None, max_length=64)


class AcPostActivationQualityBagOut(BaseModel):
    bag_code: str
    quantity_kg: Decimal
    grade: Optional[str] = None
    lot_code: Optional[str] = None
    created_at: Optional[str] = None
    process: str
    values: dict[str, Any] = Field(default_factory=dict)
    saved_at: Optional[str] = None


class AcPostActivationQualitySectionOut(BaseModel):
    process: str
    process_label: str
    bags: list[AcPostActivationQualityBagOut] = Field(default_factory=list)


class AcPostActivationQualityOut(BaseModel):
    sections: list[AcPostActivationQualitySectionOut] = Field(default_factory=list)


class AcPostActivationQualitySave(BaseModel):
    process: str = Field(..., min_length=1, max_length=64)
    bag_code: str = Field(..., min_length=1, max_length=128)
    values: dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = Field(None, max_length=128)


class AcKilnParametersCreate(BaseModel):
    kiln_resource_code: Optional[str] = Field(None, max_length=64)
    production_lot_id: Optional[UUID] = None
    recorded_at: Optional[datetime] = None
    zone1_temp_c: Optional[float] = None
    zone2_temp_c: Optional[float] = None
    steam_flow_kg_h: Optional[float] = None
    residence_time_min: Optional[float] = None
    o2_pct: Optional[float] = None
    kiln_temp_c: Optional[float] = None
    pressure_bar: Optional[float] = None


class AcKilnParameterReadingOut(BaseModel):
    reading_id: str
    kiln_resource_code: str
    recorded_at: datetime
    readings: dict[str, Any] = Field(default_factory=dict)


class AcScreeningCreate(BaseModel):
    production_lot_id: UUID
    mesh_size: str = "8x30"
    overs_kg: Optional[float] = None
    fines_kg: Optional[float] = None
    good_kg: Optional[float] = None


class AcGradeSeparationCreate(BaseModel):
    production_lot_id: UUID
    grade_code: str = Field(..., min_length=1, max_length=64)
    separated_kg: Optional[float] = Field(None, ge=0)
    grade_yield_pct: Optional[float] = Field(None, ge=0, le=100)
    overs_grade_kg: Optional[float] = Field(None, ge=0)
    fines_grade_kg: Optional[float] = Field(None, ge=0)


class AcQualityTestCreate(BaseModel):
    production_lot_id: UUID
    iodine_mg_g: Optional[Decimal] = None
    ash_pct: Optional[Decimal] = None
    moisture_pct: Optional[Decimal] = None
    bulk_density: Optional[Decimal] = None
    remarks: Optional[str] = None
    status: str = "OPEN"

    @field_validator(
        "iodine_mg_g",
        "ash_pct",
        "moisture_pct",
        "bulk_density",
        mode="before",
    )
    @classmethod
    def _coerce_measurement(cls, value):
        if value is None or value == "":
            return None
        return value


class AcKilnStatusOut(BaseModel):
    resource_code: str
    resource_name: str
    status: str
    active_lot_code: Optional[str] = None
    active_lot_kg: Optional[Decimal] = None
    loaded_kg: Optional[Decimal] = None
    monthly_capacity_kg: Optional[int] = None
    feed_events: list[Any] = Field(default_factory=list)
    last_reading_at: Optional[datetime] = None


class AcRawMaterialStatusOut(BaseModel):
    ordered_kg: Decimal
    charged_kg: Decimal
    pending_kg: Decimal
    open_order_count: int


class AcProcessStepOut(BaseModel):
    step_order: int
    label: str
    path: str
    capability_code: Optional[str] = None
    record_count: int = 0
    status: str = "pending"


class AcLotLineOut(BaseModel):
    order_code: Optional[str] = None
    production_order_code: Optional[str] = None
    lot_code: str
    lot_quantity: Decimal
    status: Optional[str] = None
    feasibility_status: Optional[str] = None
    pipeline_stage: Optional[str] = None
    is_in_progress: bool = False


class AcOpenLotOut(BaseModel):
    """Open production lots for kiln feed and execution."""

    production_lot_id: UUID
    order_code: Optional[str] = None
    production_order_code: Optional[str] = None
    lot_code: str
    lot_quantity: Decimal
    status: Optional[str] = None
    feasibility_status: Optional[str] = None
    pipeline_stage: Optional[str] = None
    routing_complete: bool = False
    kiln_resource_code: Optional[str] = None
    charged_at: Optional[str] = None
    kiln_live_status: Optional[str] = None
    kiln_feed_events: list[Any] = Field(default_factory=list)
    kiln_loaded_kg: Optional[Decimal] = None
    metadata: Optional[dict[str, Any]] = None


class AcActiveOrderOut(BaseModel):
    lot_code: str
    production_order_code: Optional[str] = None
    order_code: Optional[str] = None
    lot_quantity: Decimal
    lot_status: Optional[str] = None
    pipeline_stage: Optional[str] = None
    feasibility_status: Optional[str] = None


class AcFinishedGoodsStockOut(BaseModel):
    product_id: UUID
    product_code: str
    product_name: str
    quantity_kg: Decimal
    uom: str = "KG"


class AcDeliveryCommitmentOut(BaseModel):
    finished_product_id: UUID
    product_code: str
    quantity_kg: Decimal
    stock_on_hand_kg: Decimal
    can_dispatch_from_stock: bool
    shortfall_kg: Decimal
    raw_material_available_kg: Decimal
    tentative_delivery_date: date
    manufacturing_lead_days: int
    message: str


class AcCustomerSalesOrderCreate(BaseModel):
    customer_id: UUID
    finished_product_id: UUID
    quantity: Decimal = Field(..., gt=0)
    uom: str = "KG"
    order_code: Optional[str] = Field(None, max_length=64)
    requested_delivery_date: Optional[date] = None


class AcCustomerSalesOrderCreateResponse(BaseModel):
    order: CustomerOrderOut
    line: CustomerOrderLineOut
    commitment: AcDeliveryCommitmentOut


class AcGradeStockOut(BaseModel):
    grade_code: str
    grade_label: str
    product_id: Optional[UUID] = None
    product_code: Optional[str] = None
    quantity_kg: Decimal
    uom: str = "KG"
    source: str = "finished_goods"
    stocked_lot_count: int = 0


class AcInStockBagOut(BaseModel):
    """Destoning or post-activation bag whose destination is In Stock."""

    bag_code: str
    remaining_kg: Decimal
    quantity_kg: Decimal
    grade: Optional[str] = None
    lot_code: Optional[str] = None
    product_id: Optional[UUID] = None
    product_code: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = None


class AcStockedLotOut(BaseModel):
    """Finished-goods lot ready for dispatch."""

    production_lot_id: UUID
    lot_code: str
    lot_quantity: Decimal
    status: str = "STOCKED"
    product_id: Optional[UUID] = None
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    grade_code: Optional[str] = None
    grade_label: Optional[str] = None
    mesh_size: Optional[str] = None
    order_code: Optional[str] = None
    production_order_code: Optional[str] = None
    stocked_at: Optional[str] = None


class AcOpenCustomerOrderOut(BaseModel):
    customer_order_id: UUID
    order_code: str
    customer_id: Optional[UUID] = None
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    product_id: UUID
    product_code: str
    product_name: Optional[str] = None
    ordered_kg: Decimal
    dispatched_kg: Decimal
    remaining_kg: Decimal
    stock_on_hand_kg: Decimal
    can_dispatch_from_stock: bool
    order_status: Optional[str] = None
    requested_delivery_date: Optional[date] = None


class AcRecentDispatchOut(BaseModel):
    dispatch_id: str
    order_code: Optional[str] = None
    lot_code: Optional[str] = None
    quantity_kg: Decimal = Decimal("0")
    dispatch_date: Optional[datetime] = None
    customer_code: Optional[str] = None
    vehicle_number: Optional[str] = None


class AcDispatchFromOrderCreate(BaseModel):
    customer_order_id: UUID
    quantity_kg: Decimal = Field(..., gt=0)
    lot_code: Optional[str] = Field(None, max_length=64)
    bag_code: Optional[str] = Field(None, max_length=128)
    grade_code: Optional[str] = Field(None, max_length=64)
    vehicle_number: Optional[str] = Field(None, max_length=64)
    transporter_name: Optional[str] = Field(None, max_length=128)
    remarks: Optional[str] = None


class AcDispatchFromOrderResponse(BaseModel):
    dispatch_id: str
    order_code: str
    lot_code: str
    grade_code: Optional[str] = None
    quantity_kg: Decimal
    remaining_on_order_kg: Decimal
    order_status: str
    stock_on_hand_after_kg: Decimal


class AcMakeToStockCreate(BaseModel):
    quantity: Decimal = Field(..., gt=0)
    uom: str = "KG"
    inward_order_id: Optional[UUID] = None
    finished_product_id: Optional[UUID] = None
    production_order_code: Optional[str] = Field(None, max_length=64)
    lot_quantities: Optional[list[Decimal]] = Field(
        None,
        min_length=1,
        description="Split release into multiple kiln-feed lots; must sum to quantity.",
    )
    lot_splits: Optional[list["AcGradeLotSplit"]] = Field(
        None,
        min_length=1,
        description="Grade-labelled lot splits from crusher output; must sum to quantity.",
    )


class AcGradeLotSplit(BaseModel):
    grade_label: str = Field(..., min_length=1, max_length=64)
    quantity_kg: Decimal = Field(..., gt=0)


class AcMakeToStockCreateResponse(BaseModel):
    order: CustomerOrderOut
    line: CustomerOrderLineOut
    production_order: ProductionOrderOut
    production_lot: Optional[ProductionLotOut] = None
    production_lots: list[ProductionLotOut] = Field(default_factory=list)


class AcRawMaterialTypeOperation(BaseModel):
    operation_sequence: int = Field(..., gt=0)
    operation_name: str = Field(..., min_length=1, max_length=256)
    operation_code: str = Field(..., min_length=1, max_length=64)
    process_step: str = Field(..., min_length=1, max_length=64)
    is_mandatory: bool = True


class AcRawMaterialProcessParameter(BaseModel):
    key: str = Field(..., min_length=1, max_length=128)
    label: str = Field(..., min_length=1, max_length=256)
    unit: Optional[str] = Field(None, max_length=32)
    default_value: Optional[str] = Field(None, max_length=128)
    used_at: str = Field(default="feasibility", max_length=32)
    process_step: Optional[str] = Field(None, max_length=64)
    operation_code: Optional[str] = Field(
        None,
        max_length=64,
        description="When set, parameter applies only to this routing operation code.",
    )
    ontology_predicate: Optional[str] = Field(None, max_length=64)
    predicate_uri: Optional[str] = Field(None, max_length=256)
    subject_uri_template: Optional[str] = Field(None, max_length=256)
    object_datatype: Optional[str] = Field(None, max_length=128)
    mandatory: bool = False


class AcRawMaterialTypeUsageOut(BaseModel):
    inward_receipt_count: int = 0
    production_lot_count: int = 0
    kiln_process_started: bool = False
    dispatch_completed: bool = False
    locked: bool = False


class AcRawMaterialTypeOut(BaseModel):
    product_id: UUID
    product_code: str
    product_name: str
    finished_product_code: Optional[str] = None
    finished_product_name: Optional[str] = None
    finished_product_id: Optional[UUID] = None
    routing_code: Optional[str] = None
    routing_id: Optional[UUID] = None
    operations: list = Field(default_factory=list)
    inbound_operations: list = Field(default_factory=list)
    process_parameters: list = Field(default_factory=list)
    status: str = "ACTIVE"
    is_obsolete: bool = False
    usage: Optional[AcRawMaterialTypeUsageOut] = None


AcMastersOut.model_rebuild()


class AcRawMaterialTypeCreate(BaseModel):
    product_code: Optional[str] = Field(None, max_length=64)
    product_name: str = Field(..., min_length=1, max_length=256)
    finished_product_code: Optional[str] = Field(None, max_length=64)
    finished_product_name: Optional[str] = Field(None, max_length=256)
    routing_code: Optional[str] = Field(None, max_length=64)
    operations: list[AcRawMaterialTypeOperation] = Field(default_factory=list)
    inbound_operations: list[AcRawMaterialTypeOperation] = Field(default_factory=list)
    process_parameters: list[AcRawMaterialProcessParameter] = Field(default_factory=list)


class AcRawMaterialTypeUpdate(BaseModel):
    product_name: Optional[str] = Field(None, min_length=1, max_length=256)
    finished_product_name: Optional[str] = Field(None, min_length=1, max_length=256)
    operations: Optional[list[AcRawMaterialTypeOperation]] = None
    inbound_operations: Optional[list[AcRawMaterialTypeOperation]] = None
    process_parameters: Optional[list[AcRawMaterialProcessParameter]] = None


class AcDashboardOut(BaseModel):
    yield_summary: ActivatedCarbonYieldSummaryOut
    raw_material: AcRawMaterialStatusOut
    kilns: list[AcKilnStatusOut] = Field(default_factory=list)
    process_steps: list[AcProcessStepOut] = Field(default_factory=list)
    lot_lines: list[AcLotLineOut] = Field(default_factory=list)
    active_orders: list[AcActiveOrderOut] = Field(default_factory=list)
    quality_check_count: int = 0
    dispatch_count: int = 0
    dispatched_kg_total: Decimal = Decimal("0")
    finished_goods_stock_kg: Decimal = Decimal("0")
    grade_stock: list["AcGradeStockOut"] = Field(default_factory=list)
    open_customer_orders: list["AcOpenCustomerOrderOut"] = Field(default_factory=list)
    recent_dispatches: list["AcRecentDispatchOut"] = Field(default_factory=list)
    kiln_parameter_definitions: list[AcKilnParameterDefinition] = Field(default_factory=list)
    utilization_rag: Optional["AcIsa95UtilizationRagOut"] = None


class ChemReactorParameterDefinition(BaseModel):
    key: str
    label: str
    unit: str = ""


class ChemBatchSummaryOut(BaseModel):
    lot_count: int
    total_planned_quantity: Decimal
    total_lot_quantity: Decimal
    average_yield_pct: Optional[Decimal] = None
    industry_template_code: str


class ChemReactorStatusOut(BaseModel):
    resource_code: str
    resource_name: str
    status: str
    active_lot_code: Optional[str] = None
    active_lot_kg: Optional[Decimal] = None
    last_reading_at: Optional[datetime] = None


class ChemRawMaterialStatusOut(BaseModel):
    ordered_kg: Decimal
    charged_kg: Decimal
    pending_kg: Decimal
    open_order_count: int


class ChemProcessStepOut(BaseModel):
    step_order: int
    label: str
    path: str
    capability_code: Optional[str] = None
    record_count: int = 0
    status: str = "pending"


class ChemLotLineOut(BaseModel):
    order_code: Optional[str] = None
    production_order_code: Optional[str] = None
    lot_code: str
    lot_quantity: Decimal
    status: Optional[str] = None
    feasibility_status: Optional[str] = None
    pipeline_stage: Optional[str] = None
    is_in_progress: bool = False


class ChemDashboardOut(BaseModel):
    batch_summary: ChemBatchSummaryOut
    raw_material: ChemRawMaterialStatusOut
    reactors: list[ChemReactorStatusOut] = Field(default_factory=list)
    process_steps: list[ChemProcessStepOut] = Field(default_factory=list)
    lot_lines: list[ChemLotLineOut] = Field(default_factory=list)
    quality_check_count: int = 0
    dispatch_count: int = 0
    finished_goods_stock_kg: Decimal = Decimal("0")
    reactor_parameter_definitions: list[ChemReactorParameterDefinition] = Field(
        default_factory=list
    )


class AcAssignableRoleOut(BaseModel):
    role_code: str
    label: str


class AcAssignableRolesOut(BaseModel):
    items: list[AcAssignableRoleOut] = Field(default_factory=list)
    login_suffix: str = "@grcarbons"


class AcTenantUserOut(BaseModel):
    user_id: UUID
    username: Optional[str] = None
    email: str
    display_name: Optional[str] = None
    role_code: str
    role_label: str
    is_active: bool = True
    cognito_linked: bool = False
    created_at: Optional[datetime] = None


class AcTenantUserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    email: str = Field(..., min_length=3, max_length=320)
    display_name: Optional[str] = Field(None, max_length=256)
    role_code: str = Field(..., min_length=3, max_length=64)


class AcTenantUserCreateResponse(AcTenantUserOut):
    temporary_password: Optional[str] = None
    cognito_provisioned: bool = False
    cognito_message: Optional[str] = None
