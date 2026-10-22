"""Activated Carbon industry API namespace — adapter over common MES tables."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ac_privileges import (
    assert_can_complete_inbound_step,
    assert_quality_records_lab,
    assert_supervisor_raises_debit_note,
    assert_rms_engineer_records_bags,
    assert_rms_engineer_records_outward,
    require_ac_activation_qc,
    require_ac_activation_run,
    require_ac_destoning_ctc,
    require_ac_dispatch,
    require_ac_post_qc,
    require_ac_post_run,
    require_ac_quality,
    require_ac_gate_receipt,
    require_ac_rms,
    user_can_see_supplier,
    visible_supplier_row,
    visible_supplier_rows,
)
from app.core.capability_guard import require_any_capability, require_capability
from app.core.dependencies import (
    UserContext,
    get_current_user,
    get_mes_core_db,
    get_tenant_context,
    require_nyra_services,
    require_plant_admin,
)
from app.core.exceptions import ConflictError, ValidationError, WorkflowError
from app.core.openapi_tags import Tags
from app.core.tenant_context import TenantContext
from app.schemas.mes_core.schemas import (
    AcAssignableRolesOut,
    AcDashboardOut,
    AcKilnFeedLotCreate,
    AcKilnFeedBagQcCreate,
    AcKilnFeedBagQcOut,
    AcKilnOutputBagQcCreate,
    AcKilnOutputBagQcOut,
    AcDestonerCreate,
    AcDestonerDailyCtcOut,
    AcDestonerDailyCtcSave,
    AcKilnSetpointsOut,
    AcKilnSetpointsSave,
    AcWorkOrderCreate,
    AcWorkOrderListOut,
    AcWorkOrderOut,
    AcDestoningLoadCreate,
    AcDestoningOutputCreate,
    AcDestoningStateOut,
    AcDestoningBagQcCreate,
    AcDestoningBagQcOut,
    AcPostActivationLoadCreate,
    AcPostActivationOutputCreate,
    AcPostActivationQualityBagOut,
    AcPostActivationQualityOut,
    AcPostActivationQualitySave,
    AcPostActivationStateOut,
    AcKilnOutputBagCreate,
    AcKilnOutputBagOut,
    AcKilnOutputListOut,
    AcKilnParameterDefinition,
    AcKilnParameterDefinitionCreate,
    AcKilnCreate,
    AcKilnOut,
    AcPlantResourceOut,
    AcKilnParametersCreate,
    AcKilnReadingApproval,
    AcKilnReadingBoardOut,
    AcKilnParameterReadingOut,
    AcMastersOut,
    AcMaterialTraceOptionsOut,
    AcMaterialTraceOut,
    AcQualityTestCreate,
    AcCustomerSalesOrderCreate,
    AcCustomerSalesOrderCreateResponse,
    AcDispatchFromOrderCreate,
    AcDispatchFromOrderResponse,
    AcGradeStockOut,
    AcInStockBagOut,
    AcInStockWorkOrderMove,
    AcInStockWorkOrderMoveOut,
    AcOpenCustomerOrderOut,
    AcStockedLotOut,
    AcTenantUserCreate,
    AcTenantUserCreateResponse,
    AcTenantUserUpdate,
    AcTenantUserNicknameSave,
    AcTenantUserOut,
    AcUserNicknameOut,
    AcDeliveryCommitmentOut,
    AcFinishedGoodsStockOut,
    AcMakeToStockCreate,
    AcMakeToStockCreateResponse,
    AcOpenLotOut,
    AcRawMaterialInwardCreate,
    AcRawMaterialInwardCreateResponse,
    AcRawMaterialQcCreate,
    AcRawMaterialQcOut,
    AcInboundStepCompleteCreate,
    AcInboundExecutionOut,
    AcDebitNoteCreate,
    AcRawMaterialCrushCreate,
    AcRawMaterialCrushOut,
    AcInitialQcCreate,
    AcInitialQcOut,
    AcInboundWorkflowOut,
    AcInwardBagCreate,
    AcInwardBagAutoCreate,
    AcInwardBagOut,
    AcInwardBagReconcileCreate,
    AcInwardGradeSeparationCreate,
    AcWeightToCrusherCreate,
    AcCrusherOutputCreate,
    AcCrusherOutputOut,
    AcInboundAdminOut,
    AcInboundAdminUpdate,
    AcIsa95UtilizationRagOut,
    AcIsa95UtilizationRagUpdate,
    AcProcessRulesOut,
    AcProcessRulesUpdate,
    AcMeshGradeMapOut,
    AcMeshGradeMapUpdate,
    AcInwardBagFeedCreate,
    AcRawMaterialTypeCreate,
    AcRawMaterialTypeOut,
    AcRawMaterialTypeUpdate,
    AcScreeningCreate,
    AcGradeSeparationCreate,
    ActivatedCarbonYieldSummaryOut,
    CustomerCreate,
    CustomerOrderOut,
    CustomerOut,
    SupplierCreate,
    SupplierOut,
    OperationExecutionOut,
    ProductionLotOut,
    ProductionOrderOut,
    QualityCheckOut,
    ResourceCreate,
    ResourceOut,
    ResourceUpdate,
    TrnDispatchCreate,
    TrnDispatchOut,
    TrnDispatchUpdate,
    TripleOut,
)
from app.schemas.dispatch import DispatchCreate, DispatchOut
from app.schemas.traceability import TraceabilityResponse
from app.services.industry.activated_carbon import adapter as ac_adapter
from app.services.industry.activated_carbon import post_activation as ac_post_activation
from app.services.industry.activated_carbon import users as ac_users
from app.services.industry.activated_carbon import kiln_parameters_catalog as ac_kiln_catalog
from app.services.industry.activated_carbon import raw_material_types as ac_raw_material_types
from app.services.industry.activated_carbon import inbound_admin as ac_inbound_admin
from app.services.industry.activated_carbon import isa95_rag as ac_isa95_rag
from app.services.industry.activated_carbon import process_rules as ac_process_rules
from app.services.industry.activated_carbon import mesh_grade as ac_mesh_grade
from app.services.industry.activated_carbon import inbound_workflow as ac_inbound_workflow
from app.services.industry.activated_carbon import routing_workflow as ac_routing
from app.services.mes_core import dispatch_workflow as mes_core_dispatch
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core import feasibility as mes_core_feasibility
from app.services.mes_core.feasibility import is_ready_for_scheduling
from app.services.mes_core import trn_dispatch as mes_core_trn_dispatch

router = APIRouter(prefix="/api/activated-carbon", tags=[Tags.ACTIVATED_CARBON])

_AC_RAW = require_capability("AC_RAW_MATERIAL_INWARD")
_AC_RAW_QC = require_capability("AC_RAW_MATERIAL_QC")
_AC_KILN_FEED = require_capability("AC_KILN_FEED")
_AC_KILN_PARAMS = require_capability("AC_HOURLY_KILN_PARAMETERS")
_AC_SCREENING = require_capability("AC_SCREENING")
_AC_QC = require_capability("AC_QUALITY_TESTING")
_AC_YIELD = require_capability("AC_YIELD_ANALYSIS")
_AC_TRACE = require_capability("AC_TRACEABILITY")
_AC_KG = require_capability("AC_KNOWLEDGE_GRAPH")
_AC_MASTERS = require_any_capability(
    "AC_RAW_MATERIAL_INWARD",
    "AC_KILN_FEED",
    "AC_HOURLY_KILN_PARAMETERS",
    "AC_SCREENING",
    "AC_QUALITY_TESTING",
    "AC_YIELD_ANALYSIS",
    "AC_TRACEABILITY",
)


@router.get(
    "/raw-material-inward",
    response_model=List[CustomerOrderOut],
    summary="Raw material inward / demand orders",
)
def raw_material_inward(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = Depends(get_current_user),
):
    return visible_supplier_rows(user, ac_adapter.list_raw_material_inward(db, tenant))


@router.get(
    "/dashboard",
    response_model=AcDashboardOut,
    summary="Production dashboard KPIs, kiln status, and process flow",
)
def ac_dashboard(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.get_dashboard_summary(db, tenant)


@router.get(
    "/open-lots",
    response_model=List[AcOpenLotOut],
    summary="Open production lots for feasibility, kiln feed, and routing",
)
def ac_open_lots(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.list_open_production_lots(db, tenant)


@router.get(
    "/masters",
    response_model=AcMastersOut,
    summary="Dropdown masters for Activated Carbon data entry",
)
def ac_masters(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.get_masters(db, tenant)


@router.post(
    "/masters/kiln-parameters",
    response_model=AcKilnParameterDefinition,
    status_code=status.HTTP_201_CREATED,
    summary="Add kiln parameter to workspace catalog",
)
def ac_add_kiln_parameter(
    payload: AcKilnParameterDefinitionCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_kiln_catalog.add_kiln_parameter_definition(db, tenant, payload)
    except ConflictError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/masters/kilns",
    response_model=AcKilnOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register activation kiln (resource + equipment)",
)
def ac_create_kiln(
    payload: AcKilnCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_adapter.create_kiln(db, tenant, payload)
    except ValidationError:
        raise
    except ConflictError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/masters/destoners",
    response_model=ResourceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register destoning machine",
)
def ac_create_destoner(
    payload: AcDestonerCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_adapter.create_destoner(db, tenant, payload)
    except ValidationError:
        raise
    except ConflictError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/masters/resources",
    response_model=AcPlantResourceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register plant resource (machine, tool, or labor pool)",
)
def ac_create_resource(
    payload: ResourceCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_adapter.create_plant_resource(db, tenant, payload)
    except ValidationError:
        raise
    except ConflictError as exc:
        raise ValidationError(str(exc)) from exc


@router.put(
    "/masters/resources/{resource_id}",
    response_model=ResourceOut,
    summary="Update plant resource monthly designed capacity",
)
def ac_update_resource(
    resource_id: UUID,
    payload: ResourceUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    return ac_adapter.update_plant_resource(db, tenant, resource_id, payload)


@router.get(
    "/lots/{lot_code}/routing-plan",
    summary="Preview active product routing and work-order state for a lot",
)
def ac_lot_routing_plan(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    try:
        return ac_routing.get_lot_routing_plan(db, tenant, lot_code)
    except WorkflowError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/lots/{lot_code}/generate-route",
    summary="Materialise routing operations as shop-floor work orders",
)
def ac_generate_lot_route(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_activation_run(),
):
    try:
        return ac_routing.generate_lot_route(db, tenant, lot_code)
    except WorkflowError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/lots/{lot_code}/feasibility/run",
    summary="Run feasibility check and auto-generate shop-floor route when the lot passes",
)
def ac_run_feasibility_and_prepare_execution(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_activation_run(),
):
    """Persist feasibility results; materialise routing work orders when the gate opens."""
    result = mes_core_feasibility.run_feasibility_check(db, tenant, lot_code)
    route_payload = None
    if is_ready_for_scheduling(db, tenant, lot_code):
        try:
            route_payload = ac_routing.generate_lot_route(db, tenant, lot_code)
        except WorkflowError:
            route_payload = None
    out = result.model_dump()
    out["route_generated"] = route_payload is not None
    if route_payload:
        out["route"] = route_payload
    return out


@router.get(
    "/customers",
    response_model=List[CustomerOut],
    summary="Customers for Activated Carbon masters",
)
def ac_list_customers(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return mes_core_entities.list_customers(db, tenant)


@router.post(
    "/customers",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create customer (Activated Carbon masters)",
)
def ac_create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_plant_admin(),
):
    return ac_adapter.create_ac_customer(db, tenant, payload)


@router.get(
    "/suppliers",
    response_model=List[SupplierOut],
    summary="Suppliers for raw material inward",
)
def ac_list_suppliers(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = Depends(get_current_user),
):
    if not user_can_see_supplier(user):
        return []
    return mes_core_entities.list_suppliers(db, tenant)


@router.post(
    "/suppliers",
    response_model=SupplierOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create supplier (Activated Carbon masters)",
)
def ac_create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_plant_admin(),
):
    return ac_adapter.create_ac_supplier(db, tenant, payload)


@router.get(
    "/masters/raw-material-types",
    response_model=List[AcRawMaterialTypeOut],
    summary="Raw material types with linked routing",
)
def ac_list_raw_material_types(
    active_only: bool = False,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_raw_material_types.list_raw_material_types(
        db, tenant, active_only=active_only
    )


@router.post(
    "/masters/raw-material-types",
    response_model=AcRawMaterialTypeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create raw material type with auto-generated codes when omitted",
)
def ac_create_raw_material_type(
    payload: AcRawMaterialTypeCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_raw_material_types.create_raw_material_type(db, tenant, payload)
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(str(exc)) from exc


@router.get(
    "/masters/raw-material-types/{product_id}",
    response_model=AcRawMaterialTypeOut,
    summary="Single raw material type with linked routing",
)
def ac_get_raw_material_type(
    product_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_raw_material_types.get_raw_material_type(db, tenant, product_id)


@router.put(
    "/masters/raw-material-types/{product_id}",
    response_model=AcRawMaterialTypeOut,
    summary="Update raw material type routing and parameters",
)
def ac_update_raw_material_type(
    product_id: UUID,
    payload: AcRawMaterialTypeUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_raw_material_types.update_raw_material_type(
            db, tenant, product_id, payload
        )
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/masters/raw-material-types/{product_id}/obsolete",
    response_model=AcRawMaterialTypeOut,
    summary="Mark raw material type obsolete (preserves history, blocks new inward)",
)
def ac_mark_raw_material_type_obsolete(
    product_id: UUID,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    try:
        return ac_raw_material_types.mark_raw_material_type_obsolete(
            db, tenant, product_id
        )
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(str(exc)) from exc


@router.get(
    "/dispatches",
    response_model=List[DispatchOut],
    summary="Dispatch history for Activated Carbon",
)
def ac_list_dispatches(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return mes_core_dispatch.list_dispatches(db, tenant)


@router.post(
    "/dispatches",
    response_model=DispatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create dispatch shipment",
)
def ac_create_dispatch(
    payload: DispatchCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_dispatch(),
):
    try:
        return mes_core_dispatch.create_dispatch(db, tenant, payload)
    except WorkflowError as exc:
        raise ValidationError(str(exc)) from exc


@router.get(
    "/dispatch",
    response_model=List[TrnDispatchOut],
    summary="Dispatch records (trn.dispatch)",
)
def ac_list_dispatch_records(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return mes_core_trn_dispatch.list_dispatches(db, tenant)


@router.post(
    "/dispatch",
    response_model=TrnDispatchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create dispatch record (trn.dispatch)",
)
def ac_create_dispatch_record(
    payload: TrnDispatchCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_dispatch(),
):
    return mes_core_trn_dispatch.create_dispatch(db, tenant, payload)


@router.put(
    "/dispatch/{dispatch_id}",
    response_model=TrnDispatchOut,
    summary="Update dispatch record (trn.dispatch)",
)
def ac_update_dispatch_record(
    dispatch_id: UUID,
    payload: TrnDispatchUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_dispatch(),
):
    return mes_core_trn_dispatch.update_dispatch(db, tenant, dispatch_id, payload)


@router.post(
    "/raw-material-inward",
    response_model=AcRawMaterialInwardCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record raw material inward (supplier receipt)",
)
def create_raw_material_inward(
    payload: AcRawMaterialInwardCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_gate_receipt(),
):
    return ac_adapter.create_raw_material_inward(db, tenant, payload)


@router.post(
    "/manufacturing-orders",
    response_model=AcMakeToStockCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Release inward material to production (make-to-stock, not a customer PO)",
)
def create_make_to_stock_order(
    payload: AcMakeToStockCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_rms(),
):
    return ac_adapter.create_make_to_stock_production_order(db, tenant, payload)


@router.get(
    "/finished-goods-stock",
    response_model=List[AcFinishedGoodsStockOut],
    summary="Finished goods on hand after lot execution completes",
)
def list_finished_goods_stock(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.list_finished_goods_stock(db, tenant)


@router.get(
    "/customer-orders/commitment",
    response_model=AcDeliveryCommitmentOut,
    summary="Stock check and tentative delivery date for a customer quantity",
)
def customer_order_commitment(
    finished_product_id: UUID,
    quantity: Decimal = Query(..., gt=0),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.evaluate_delivery_commitment(
        db,
        tenant,
        finished_product_id=finished_product_id,
        quantity=quantity,
    )


@router.post(
    "/customer-sales-orders",
    response_model=AcCustomerSalesOrderCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Customer PO for finished goods — checks stock and promises a date if needed",
)
def create_customer_sales_order(
    payload: AcCustomerSalesOrderCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_dispatch(),
):
    return ac_adapter.create_customer_sales_order(db, tenant, payload)


@router.get(
    "/customer-sales-orders",
    response_model=List[AcOpenCustomerOrderOut],
    summary="Open customer POs eligible for dispatch",
)
def list_open_customer_sales_orders(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.list_open_customer_sales_orders(db, tenant)


@router.get(
    "/grade-stock",
    response_model=List[AcGradeStockOut],
    summary="Grade-wise finished goods stock on hand",
)
def list_grade_stock(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.list_grade_wise_stock(db, tenant)


@router.get(
    "/stocked-lots",
    response_model=List[AcStockedLotOut],
    summary="Stocked production lots available for dispatch",
)
def list_stocked_lots(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.list_stocked_lots_for_dispatch(db, tenant)


@router.get(
    "/in-stock-bags",
    response_model=List[AcInStockBagOut],
    summary="Bags marked In Stock and available for work-order dispatch",
)
def list_in_stock_bags(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.list_in_stock_bags_for_dispatch(db, tenant)


@router.post(
    "/in-stock/reassign-work-order",
    response_model=AcInStockWorkOrderMoveOut,
    summary="Move an In Stock bag to another work order of the same grade",
)
def reassign_in_stock_work_order(
    payload: AcInStockWorkOrderMove,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = require_ac_destoning_ctc(),
):
    return ac_post_activation.reassign_in_stock_work_order(
        db,
        tenant,
        bag_code=payload.bag_code,
        work_order_code=payload.work_order_code,
        user_id=user.username,
    )


@router.post(
    "/dispatch-from-order",
    response_model=AcDispatchFromOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ship from In Stock bags by work order, optionally against a historical PO",
)
def create_dispatch_from_order(
    payload: AcDispatchFromOrderCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_ac_dispatch(),
):
    try:
        return ac_adapter.create_ac_dispatch_from_order(db, tenant, payload)
    except ValidationError:
        raise
    except WorkflowError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/raw-material-inward/backfill-production-orders",
    summary="Create missing production orders for existing inward records",
)
def backfill_inward_production_orders(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_rms(),
):
    return ac_adapter.backfill_inward_production_orders(db, tenant)


@router.get(
    "/raw-material-qc",
    response_model=List[AcRawMaterialQcOut],
    summary="Raw material QC records for inward orders",
)
def list_raw_material_qc(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW_QC),
    user: UserContext = Depends(get_current_user),
):
    return visible_supplier_rows(user, ac_adapter.list_raw_material_qc(db, tenant))


@router.post(
    "/raw-material-qc",
    response_model=AcRawMaterialQcOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record raw material QC for an inward order",
)
def create_raw_material_qc(
    payload: AcRawMaterialQcCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW_QC),
    user: UserContext = Depends(get_current_user),
):
    if settings.auth_enabled:
        assert_quality_records_lab(user)
    return visible_supplier_row(user, ac_adapter.create_raw_material_qc(db, tenant, payload))


@router.get(
    "/raw-material-inbound-execution",
    response_model=List[AcInboundExecutionOut],
    summary="Inward orders with configurable inbound prep step status",
)
def list_inbound_execution(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = Depends(get_current_user),
):
    return visible_supplier_rows(user, ac_adapter.list_inbound_execution(db, tenant))


@router.post(
    "/raw-material-inbound-execution",
    response_model=AcInboundExecutionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Complete an inbound prep step before raw material QC",
)
def complete_inbound_execution_step(
    payload: AcInboundStepCompleteCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = Depends(get_current_user),
):
    if settings.auth_enabled:
        assert_can_complete_inbound_step(user, payload.operation_code)
    try:
        row = ac_adapter.complete_inbound_execution_step(db, tenant, payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return visible_supplier_row(user, row)


@router.post(
    "/raw-material-inbound-execution/{customer_order_id}/debit-note",
    response_model=AcInboundExecutionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a supplier debit note for short weight or high moisture",
)
def raise_inward_debit_note(
    customer_order_id: UUID,
    payload: AcDebitNoteCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = Depends(get_current_user),
):
    if settings.auth_enabled:
        assert_supervisor_raises_debit_note(user)
    row = ac_adapter.raise_inward_debit_note(db, tenant, customer_order_id, payload)
    return visible_supplier_row(user, row)


@router.get(
    "/raw-material-crushing",
    response_model=List[AcRawMaterialCrushOut],
    summary="Inward orders with crushing status (before QC)",
)
def list_raw_material_crushing(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = Depends(get_current_user),
):
    return visible_supplier_rows(user, ac_adapter.list_raw_material_crushing(db, tenant))


@router.post(
    "/raw-material-crushing",
    response_model=AcRawMaterialCrushOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record crushing / sizing before raw material QC",
)
def create_raw_material_crushing(
    payload: AcRawMaterialCrushCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = require_ac_rms(),
):
    return visible_supplier_row(user, ac_adapter.create_raw_material_crush(db, tenant, payload))


@router.get(
    "/raw-material-inbound-workflow",
    response_model=List[AcInboundWorkflowOut],
    summary="Inward workflow status (initial QC, weight to crusher, crusher)",
)
def list_raw_material_inbound_workflow(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
):
    return ac_inbound_workflow.list_inbound_workflow(db, tenant)


@router.post(
    "/raw-material-initial-qc",
    response_model=AcInitialQcOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record initial QC after raw material inward",
)
def create_raw_material_initial_qc(
    payload: AcInitialQcCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW_QC),
    user: UserContext = Depends(get_current_user),
):
    if settings.auth_enabled:
        assert_quality_records_lab(user)
    return ac_inbound_workflow.create_initial_qc(db, tenant, payload)


@router.get(
    "/inward-bags",
    response_model=List[AcInwardBagOut],
    summary="List grade-wise inward bags",
)
def list_inward_bags(
    order_code: Optional[str] = Query(default=None),
    customer_order_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
):
    return ac_inbound_workflow.list_inward_bags(
        db, tenant, order_code=order_code, customer_order_id=customer_order_id
    )


@router.post(
    "/inward-bags/auto-rms",
    response_model=List[AcInwardBagOut],
    status_code=status.HTTP_201_CREATED,
    summary="Automatically split inward weight into 500 kg RMS bags",
)
def auto_create_rms_bags(
    payload: AcInwardBagAutoCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = require_ac_rms(),
):
    if settings.auth_enabled:
        assert_rms_engineer_records_bags(user)
    return ac_inbound_workflow.auto_create_rms_bags(db, tenant, payload.customer_order_id)


@router.post(
    "/inward-bags",
    response_model=AcInwardBagOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a grade-wise bag against an inward order",
)
def create_inward_bag(
    payload: AcInwardBagCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = require_ac_rms(),
):
    if settings.auth_enabled:
        if (payload.grade or "").strip():
            assert_rms_engineer_records_outward(user)
        else:
            assert_rms_engineer_records_bags(user)
    return ac_inbound_workflow.create_inward_bag(db, tenant, payload)


@router.delete(
    "/inward-bags/{bag_id}",
    response_model=AcInboundWorkflowOut,
    summary="Remove a bag before reconciliation",
)
def delete_inward_bag(
    bag_id: UUID,
    customer_order_id: UUID = Query(...),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    user: UserContext = require_ac_rms(),
):
    if settings.auth_enabled:
        assert_rms_engineer_records_outward(user)
    return ac_inbound_workflow.delete_inward_bag(
        db, tenant, customer_order_id=customer_order_id, bag_id=bag_id
    )


@router.post(
    "/inward-bags/feed-crusher",
    response_model=AcInwardBagOut,
    summary="Feed one RMS bag into the crusher",
)
def feed_inward_bag_to_crusher(
    payload: AcInwardBagFeedCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_rms(),
):
    return ac_inbound_workflow.feed_inward_bag_to_crusher(db, tenant, payload)


@router.get(
    "/inbound-admin",
    response_model=AcInboundAdminOut,
    summary="Rotary inventory and RM outward split catalog",
)
def get_inbound_admin(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
):
    return ac_inbound_admin.get_inbound_admin(db, tenant)


@router.put(
    "/inbound-admin",
    response_model=AcInboundAdminOut,
    summary="Save rotary inventory and RM outward splits (admin)",
)
def put_inbound_admin(
    payload: AcInboundAdminUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    return ac_inbound_admin.save_inbound_admin(db, tenant, payload.model_dump())


@router.get(
    "/masters/utilization-rag",
    response_model=AcIsa95UtilizationRagOut,
    summary="ISA-95 red/amber/green limits for machine monthly output vs designed",
)
def get_utilization_rag(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_isa95_rag.get_utilization_rag(db, tenant)


@router.put(
    "/masters/utilization-rag",
    response_model=AcIsa95UtilizationRagOut,
    summary="Save ISA-95 red/amber/green limits for machine utilization",
)
def put_utilization_rag(
    payload: AcIsa95UtilizationRagUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    return ac_isa95_rag.save_utilization_rag(db, tenant, payload.model_dump())


@router.get(
    "/masters/process-rules",
    response_model=AcProcessRulesOut,
    summary="Bag, moisture, CTC, and destoning routing rules",
)
def get_process_rules(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_process_rules.get_process_rules(db, tenant)


@router.put(
    "/masters/process-rules",
    response_model=AcProcessRulesOut,
    summary="Save bag, moisture, CTC, and destoning routing rules",
)
def put_process_rules(
    payload: AcProcessRulesUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    return ac_process_rules.save_process_rules(db, tenant, payload.model_dump())


@router.get(
    "/masters/mesh-grade-map",
    response_model=AcMeshGradeMapOut,
    summary="Mesh-to-grade mapping (empty until GR Carbons supplies it)",
)
def get_mesh_grade_map(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_mesh_grade.get_mesh_grade_map(db, tenant)


@router.put(
    "/masters/mesh-grade-map",
    response_model=AcMeshGradeMapOut,
    summary="Save mesh-to-grade mapping when GR Carbons supplies it",
)
def put_mesh_grade_map(
    payload: AcMeshGradeMapUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    _user=require_nyra_services(),
):
    return ac_mesh_grade.save_mesh_grade_map(db, tenant, payload.model_dump())


@router.post(
    "/inward-bags/reconcile",
    response_model=AcInboundWorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reconcile bag totals to received quantity before crusher",
)
def reconcile_inward_bags(
    payload: AcInwardBagReconcileCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_rms(),
):
    return ac_inbound_workflow.reconcile_inward_bags(db, tenant, payload)


@router.post(
    "/raw-material-weight-to-crusher",
    response_model=AcInboundWorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record weight sent to crusher (reconcile against received quantity)",
)
def create_raw_material_weight_to_crusher(
    payload: AcWeightToCrusherCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_rms(),
):
    return ac_inbound_workflow.record_weight_to_crusher(db, tenant, payload)


@router.post(
    "/raw-material-grade-separation",
    response_model=AcInboundWorkflowOut,
    status_code=status.HTTP_201_CREATED,
    summary="Split remaining crusher output into production grades",
)
def create_raw_material_grade_separation(
    payload: AcInwardGradeSeparationCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_rms(),
):
    return ac_inbound_workflow.create_inward_grade_separation(db, tenant, payload)


@router.post(
    "/raw-material-crusher-output",
    response_model=AcCrusherOutputOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record crusher mesh output and scrap weights",
)
def create_raw_material_crusher_output(
    payload: AcCrusherOutputCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_RAW),
    _user=require_ac_rms(),
):
    return ac_inbound_workflow.create_crusher_output(db, tenant, payload)


@router.get(
    "/kiln-feed",
    response_model=List[ProductionLotOut],
    summary="Kiln feed lots",
)
def kiln_feed(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_kiln_feed_lots(db, tenant)


@router.post(
    "/kiln-feed",
    response_model=ProductionLotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create kiln feed production lot",
)
def create_kiln_feed(
    payload: AcKilnFeedLotCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_run(),
):
    return ac_adapter.create_kiln_feed_lot(db, tenant, payload)


@router.get(
    "/kiln-output",
    response_model=AcKilnOutputListOut,
    summary="Kiln output bags for a kiln",
)
def list_kiln_output(
    kiln_resource_code: str = Query(..., min_length=1),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_kiln_output_bags(db, tenant, kiln_resource_code)


@router.post(
    "/kiln-output",
    response_model=AcKilnOutputBagOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a kiln output bag",
)
def create_kiln_output(
    payload: AcKilnOutputBagCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_run(),
):
    return ac_adapter.create_kiln_output_bag(db, tenant, payload, _user)


@router.post(
    "/kiln-feed-bag-qc",
    response_model=AcKilnFeedBagQcOut,
    summary="Save kiln feed quality on an RM outward bag",
)
def save_kiln_feed_bag_qc(
    payload: AcKilnFeedBagQcCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_qc(),
):
    return ac_inbound_workflow.save_kiln_feed_bag_qc(db, tenant, payload)


@router.get(
    "/kiln-output-bag-qc",
    response_model=List[AcKilnOutputBagQcOut],
    summary="Kiln output bags with quality captures",
)
def list_kiln_output_bag_qc(
    kiln_resource_code: Optional[str] = Query(default=None),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_kiln_output_qc_bags(db, tenant, kiln_resource_code)


@router.post(
    "/kiln-output-bag-qc",
    response_model=AcKilnOutputBagQcOut,
    summary="Save kiln output quality on a kiln output bag",
)
def save_kiln_output_bag_qc(
    payload: AcKilnOutputBagQcCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_qc(),
):
    return ac_adapter.save_kiln_output_bag_qc(db, tenant, payload)


@router.get(
    "/destoning/daily-ctc",
    response_model=AcDestonerDailyCtcOut,
    summary="Supervisor daily CTC plan per destoner",
)
def destoning_daily_ctc(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.get_destoner_daily_ctc(db, tenant)


@router.put(
    "/destoning/daily-ctc",
    response_model=AcDestonerDailyCtcOut,
    summary="Save today's destoner CTC assignment",
)
def save_destoning_daily_ctc(
    payload: AcDestonerDailyCtcSave,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = require_ac_destoning_ctc(),
):
    return ac_adapter.save_destoner_daily_ctc(db, tenant, payload, user=user)


@router.get(
    "/kiln/setpoints",
    response_model=AcKilnSetpointsOut,
    summary="Standing kiln parameters (residence time and setpoints)",
)
def kiln_setpoints(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_adapter.get_kiln_setpoints(db, tenant)


@router.put(
    "/kiln/setpoints",
    response_model=AcKilnSetpointsOut,
    summary="Save standing kiln parameters. Values stay until changed.",
)
def save_kiln_setpoints(
    payload: AcKilnSetpointsSave,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = require_ac_destoning_ctc(),
):
    return ac_adapter.save_kiln_setpoints(db, tenant, payload, user=user)


@router.get(
    "/work-orders",
    response_model=AcWorkOrderListOut,
    summary="Activation work orders (grade, CTC, quantity)",
)
def list_work_orders(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_activation_work_orders(db, tenant)


@router.post(
    "/work-orders",
    response_model=AcWorkOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an activation work order",
)
def create_work_order(
    payload: AcWorkOrderCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = require_ac_destoning_ctc(),
):
    return ac_adapter.create_activation_work_order(db, tenant, payload, user=user)


@router.delete(
    "/work-orders/{work_order_code}",
    response_model=AcWorkOrderOut,
    summary="Delete an unused activation work order",
)
def delete_work_order(
    work_order_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = require_ac_destoning_ctc(),
):
    return ac_adapter.delete_activation_work_order(db, tenant, work_order_code)


@router.get(
    "/destoning",
    response_model=AcDestoningStateOut,
    summary="Destoning loader and kiln output input bags",
)
def destoning_state(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.get_destoning_state(db, tenant)


@router.post(
    "/destoning/load",
    response_model=AcDestoningStateOut,
    summary="Load a kiln output bag onto the de-stoner",
)
def destoning_load(
    payload: AcDestoningLoadCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_run(),
):
    return ac_adapter.load_destoning_bag(db, tenant, payload)


@router.post(
    "/destoning/unload",
    response_model=AcDestoningStateOut,
    summary="Remove a bag from the de-stoner",
)
def destoning_unload(
    payload: AcDestoningLoadCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_run(),
):
    return ac_adapter.unload_destoning_bag(db, tenant, payload)


@router.post(
    "/destoning/output",
    response_model=AcDestoningStateOut,
    summary="Create a destoning output bag",
)
def destoning_output(
    payload: AcDestoningOutputCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_run(),
):
    return ac_adapter.create_destoning_output_bag(db, tenant, payload, _user)


@router.get(
    "/destoning-bag-qc",
    response_model=List[AcDestoningBagQcOut],
    summary="Destoning output bags with quality captures",
)
def list_destoning_bag_qc(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_destoning_qc_bags(db, tenant)


@router.post(
    "/destoning-bag-qc",
    response_model=AcDestoningBagQcOut,
    summary="Save destoning quality on a DS bag",
)
def save_destoning_bag_qc(
    payload: AcDestoningBagQcCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_activation_qc(),
):
    return ac_adapter.save_destoning_bag_qc(db, tenant, payload)


@router.get(
    "/post-activation/quality",
    response_model=AcPostActivationQualityOut,
    summary="Post-activation quality bags by process",
)
def post_activation_quality(
    scope: str = Query("today"),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_post_activation_quality(db, tenant, scope=scope)


@router.post(
    "/post-activation/quality",
    response_model=AcPostActivationQualityBagOut,
    summary="Save post-activation bag quality and next destination",
)
def save_post_activation_quality(
    payload: AcPostActivationQualitySave,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_post_qc(),
):
    return ac_adapter.save_post_activation_quality(db, tenant, payload)


@router.get(
    "/post-activation/{process}",
    response_model=AcPostActivationStateOut,
    summary="Post-activation live loader for destoning output bags",
)
def post_activation_state(
    process: str,
    scope: str = Query("today"),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.get_post_activation_state(db, tenant, process, scope=scope)


@router.post(
    "/post-activation/{process}/load",
    response_model=AcPostActivationStateOut,
    summary="Load a destoning bag onto a post-activation process",
)
def post_activation_load(
    process: str,
    payload: AcPostActivationLoadCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_post_run(),
):
    return ac_adapter.load_post_activation_bag(db, tenant, process, payload)


@router.post(
    "/post-activation/{process}/unload",
    response_model=AcPostActivationStateOut,
    summary="Unload a destoning bag from a post-activation process",
)
def post_activation_unload(
    process: str,
    payload: AcPostActivationLoadCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_post_run(),
):
    return ac_adapter.unload_post_activation_bag(db, tenant, process, payload)


@router.post(
    "/post-activation/{process}/output",
    response_model=AcPostActivationStateOut,
    summary="Create a post-activation output bag with grade and weight",
)
def post_activation_output(
    process: str,
    payload: AcPostActivationOutputCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
    _user=require_ac_post_run(),
):
    return ac_adapter.create_post_activation_output_bag(db, tenant, process, payload, _user)


@router.get(
    "/kiln-feed/orders",
    response_model=List[ProductionOrderOut],
    summary="Production orders feeding kiln operations",
)
def kiln_feed_orders(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_FEED),
):
    return ac_adapter.list_kiln_production_orders(db, tenant)


@router.get(
    "/kiln-parameters",
    response_model=List[AcKilnParameterReadingOut],
    summary="Kiln parameter readings with timestamp (not lot-scoped)",
)
def kiln_parameters(
    lot_code: Optional[str] = Query(None, description="Unused — readings are kiln-scoped"),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_PARAMS),
):
    return ac_adapter.list_kiln_parameters(db, tenant, lot_code=lot_code)


@router.post(
    "/kiln-parameters",
    response_model=AcKilnParameterReadingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record kiln parameter readings with timestamp",
)
def create_kiln_parameters(
    payload: AcKilnParametersCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_PARAMS),
    user: UserContext = require_ac_activation_run(),
):
    try:
        return ac_adapter.create_kiln_parameters(db, tenant, payload, user=user)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get(
    "/kiln-parameters/board",
    response_model=AcKilnReadingBoardOut,
    summary="Current 30-minute kiln reading and any locked intervals",
)
def kiln_parameter_board(
    kiln_resource_code: str = Query(..., min_length=1),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_PARAMS),
    _user: UserContext = require_ac_activation_run(),
):
    return ac_adapter.kiln_reading_board(db, tenant, kiln_resource_code)


@router.post(
    "/kiln-parameters/approve",
    response_model=AcKilnReadingBoardOut,
    summary="Plant manager approves a missed 30-minute kiln reading",
)
def approve_kiln_parameter_slot(
    payload: AcKilnReadingApproval,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_PARAMS),
    user: UserContext = Depends(get_current_user),
):
    from app.core.auth import MES_ADMIN, MES_MANAGER, MES_PLANNER, MES_SUPER_ADMIN
    from app.core.exceptions import ForbiddenError

    if not user.has_any_role({MES_MANAGER, MES_PLANNER, MES_ADMIN, MES_SUPER_ADMIN}) and not user.is_nyra_services():
        raise ForbiddenError("A plant manager approves a missed kiln reading.")
    try:
        return ac_adapter.approve_kiln_reading(db, tenant, payload, user=user)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get(
    "/screening",
    response_model=List[OperationExecutionOut],
    summary="Screening operation executions",
)
def screening(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_SCREENING),
):
    return ac_adapter.list_screening_executions(db, tenant)


@router.post(
    "/screening",
    response_model=OperationExecutionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record screening classification",
)
def create_screening(
    payload: AcScreeningCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_SCREENING),
    _user=require_ac_post_run(),
):
    try:
        return ac_adapter.create_screening_record(db, tenant, payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post(
    "/grade-separation",
    response_model=OperationExecutionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record grade separation after screening",
)
def create_grade_separation(
    payload: AcGradeSeparationCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_SCREENING),
    _user=require_ac_post_run(),
):
    try:
        return ac_adapter.create_grade_separation_record(db, tenant, payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.get(
    "/quality-testing",
    response_model=List[QualityCheckOut],
    summary="Quality testing records",
)
def quality_testing(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_QC),
):
    return ac_adapter.list_quality_testing(db, tenant)


@router.post(
    "/quality-testing",
    response_model=QualityCheckOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record quality test for a lot",
)
def create_quality_testing(
    payload: AcQualityTestCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_QC),
    _user=require_ac_quality(),
):
    return ac_adapter.create_quality_test(db, tenant, payload)


@router.get(
    "/yield-analysis",
    response_model=ActivatedCarbonYieldSummaryOut,
    summary="Yield analysis summary",
)
def yield_analysis(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_YIELD),
):
    return ac_adapter.compute_yield_analysis(db, tenant)


@router.get(
    "/traceability/{lot_code}",
    response_model=TraceabilityResponse,
    summary="Lot traceability genealogy",
)
def traceability(
    lot_code: str,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_TRACE),
):
    return ac_adapter.get_lot_traceability(db, tenant, lot_code)


@router.get(
    "/material-trace",
    response_model=AcMaterialTraceOut,
    summary="Supplier-mapped material trace (work order, bag, inward, or dispatch)",
)
def material_trace(
    q: str = Query(..., min_length=1, description="WO-AC-*, bag code, ORD-AC-*, or DISP-AC-*"),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = Depends(get_current_user),
):
    return visible_supplier_row(user, ac_adapter.lookup_material_trace(db, tenant, q))


@router.get(
    "/material-trace/options",
    response_model=AcMaterialTraceOptionsOut,
    summary="Traceability lookup codes for the current month",
)
def material_trace_options(
    kind: str = Query("work_order", description="work_order, bag, inward, or dispatch"),
    month: Optional[str] = Query(None, description="YYYY-MM; defaults to the current month"),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
    user: UserContext = Depends(get_current_user),
):
    row = ac_adapter.list_material_trace_options(db, tenant, kind, month)
    if user_can_see_supplier(user):
        return row
    return row.model_copy(
        update={"options": [opt.model_copy(update={"label": opt.code}) for opt in row.options]}
    )


@router.get(
    "/knowledge-graph/triples",
    response_model=List[TripleOut],
    summary="Knowledge graph triple staging rows",
)
def knowledge_graph_triples(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KG),
):
    return ac_adapter.list_knowledge_graph_triples(db, tenant, limit=limit)


@router.get(
    "/users/roles",
    response_model=AcAssignableRolesOut,
    summary="MES roles the signed-in administrator may assign",
)
def ac_assignable_user_roles(
    tenant: TenantContext = Depends(get_tenant_context),
    user: UserContext = require_plant_admin(),
):
    return AcAssignableRolesOut(
        items=ac_users.assignable_roles_for_actor(user),
        login_suffix=ac_users.login_suffix_for_tenant(tenant.tenant_code),
    )


@router.get(
    "/users",
    response_model=List[AcTenantUserOut],
    summary="Users with access to this plant",
)
def ac_list_users(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _user: UserContext = require_plant_admin(),
):
    return ac_users.list_tenant_users(db, tenant)


@router.post(
    "/users",
    response_model=AcTenantUserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a plant user (Administrator)",
)
def ac_create_user(
    payload: AcTenantUserCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
    user: UserContext = require_plant_admin(),
):
    return ac_users.create_tenant_user(
        db,
        tenant,
        user,
        username=payload.username,
        email=payload.email,
        display_name=payload.display_name,
        role_code=payload.role_code,
        role_codes=payload.role_codes,
        password=payload.password,
    )


@router.put(
    "/users/{user_id}",
    response_model=AcTenantUserOut,
    summary="Edit a plant user's nickname, email, and roles",
)
def ac_update_user(
    user_id: UUID,
    payload: AcTenantUserUpdate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
    user: UserContext = require_plant_admin(),
):
    return ac_users.update_tenant_user(
        db,
        tenant,
        user,
        user_id,
        display_name=payload.display_name,
        email=payload.email,
        role_code=payload.role_code,
        role_codes=payload.role_codes,
        is_active=payload.is_active,
    )


@router.get(
    "/users/nicknames",
    response_model=List[AcUserNicknameOut],
    summary="Nicknames for people on this plant",
)
def ac_user_nicknames(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _user: UserContext = Depends(get_current_user),
):
    return ac_users.list_plant_nicknames(db, tenant)


@router.put(
    "/users/{user_id}/nickname",
    response_model=AcTenantUserOut,
    summary="Change a plant user's nickname",
)
def ac_update_user_nickname(
    user_id: UUID,
    payload: AcTenantUserNicknameSave,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _user: UserContext = require_plant_admin(),
):
    return ac_users.update_tenant_user_nickname(
        db, tenant, user_id, payload.display_name
    )
