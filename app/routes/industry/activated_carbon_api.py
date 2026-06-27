"""Activated Carbon industry API namespace — adapter over common MES tables."""

from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.capability_guard import require_any_capability, require_capability
from app.core.dependencies import (
    get_mes_core_db,
    get_tenant_context,
    require_super_admin,
    require_tenant_admin,
)
from app.core.exceptions import ConflictError, ValidationError, WorkflowError
from app.core.openapi_tags import Tags
from app.core.tenant_context import TenantContext
from app.schemas.mes_core.schemas import (
    AcDashboardOut,
    AcKilnFeedLotCreate,
    AcKilnParameterDefinition,
    AcKilnParameterDefinitionCreate,
    AcKilnCreate,
    AcKilnOut,
    AcPlantResourceOut,
    AcKilnParametersCreate,
    AcMastersOut,
    AcQualityTestCreate,
    AcCustomerSalesOrderCreate,
    AcCustomerSalesOrderCreateResponse,
    AcDispatchFromOrderCreate,
    AcDispatchFromOrderResponse,
    AcGradeStockOut,
    AcOpenCustomerOrderOut,
    AcStockedLotOut,
    AcDeliveryCommitmentOut,
    AcFinishedGoodsStockOut,
    AcMakeToStockCreate,
    AcMakeToStockCreateResponse,
    AcOpenLotOut,
    AcRawMaterialInwardCreate,
    AcRawMaterialInwardCreateResponse,
    AcRawMaterialQcCreate,
    AcRawMaterialQcOut,
    AcRawMaterialTypeCreate,
    AcRawMaterialTypeOut,
    AcRawMaterialTypeUpdate,
    AcScreeningCreate,
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
    TrnDispatchCreate,
    TrnDispatchOut,
    TrnDispatchUpdate,
    TripleOut,
)
from app.schemas.dispatch import DispatchCreate, DispatchOut
from app.schemas.traceability import TraceabilityResponse
from app.services.industry.activated_carbon import adapter as ac_adapter
from app.services.industry.activated_carbon import kiln_parameters_catalog as ac_kiln_catalog
from app.services.industry.activated_carbon import raw_material_types as ac_raw_material_types
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
):
    return ac_adapter.list_raw_material_inward(db, tenant)


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
    _user=require_tenant_admin(),
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
    _user=require_tenant_admin(),
):
    try:
        return ac_adapter.create_kiln(db, tenant, payload)
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
    _user=require_tenant_admin(),
):
    try:
        return ac_adapter.create_plant_resource(db, tenant, payload)
    except ValidationError:
        raise
    except ConflictError as exc:
        raise ValidationError(str(exc)) from exc


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
    _user=require_tenant_admin(),
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
):
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
    _user=require_tenant_admin(),
):
    return ac_adapter.create_ac_supplier(db, tenant, payload)


@router.get(
    "/masters/raw-material-types",
    response_model=List[AcRawMaterialTypeOut],
    summary="Raw material types with linked routing",
)
def ac_list_raw_material_types(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
):
    return ac_raw_material_types.list_raw_material_types(db, tenant)


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
    _user=require_super_admin(),
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
    _user=require_super_admin(),
):
    try:
        return ac_raw_material_types.update_raw_material_type(
            db, tenant, product_id, payload
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


@router.post(
    "/dispatch-from-order",
    response_model=AcDispatchFromOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ship against a customer PO from in-stock lots by grade",
)
def create_dispatch_from_order(
    payload: AcDispatchFromOrderCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_MASTERS),
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
):
    return ac_adapter.list_raw_material_qc(db, tenant)


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
):
    return ac_adapter.create_raw_material_qc(db, tenant, payload)


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
):
    return ac_adapter.create_kiln_feed_lot(db, tenant, payload)


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
    response_model=List[OperationExecutionOut],
    summary="Hourly kiln parameters via operation execution records",
)
def kiln_parameters(
    lot_code: Optional[str] = Query(None, description="Filter by lot code"),
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_PARAMS),
):
    return ac_adapter.list_kiln_parameters(db, tenant, lot_code=lot_code)


@router.post(
    "/kiln-parameters",
    response_model=OperationExecutionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record hourly kiln parameter readings",
)
def create_kiln_parameters(
    payload: AcKilnParametersCreate,
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_AC_KILN_PARAMS),
):
    try:
        return ac_adapter.create_kiln_parameters(db, tenant, payload)
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
):
    try:
        return ac_adapter.create_screening_record(db, tenant, payload)
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
