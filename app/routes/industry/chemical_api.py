"""Chemical Processing industry API namespace — adapter over common MES tables."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.capability_guard import require_any_capability
from app.core.dependencies import get_mes_core_db
from app.core.openapi_tags import Tags
from app.core.tenant_context import TenantContext
from app.schemas.mes_core.schemas import ChemDashboardOut
from app.services.industry.chemical import adapter as chem_adapter

router = APIRouter(prefix="/api/chemical", tags=[Tags.CHEMICAL])

_CHEM_READ = require_any_capability(
    "CHEM_RAW_MATERIAL_RECEIPT",
    "CHEM_REACTOR_CHARGE",
    "CHEM_REACTOR_PARAMETERS",
    "CHEM_BLEND_FORMULATION",
    "CHEM_BATCH_QC",
    "CHEM_BATCH_ANALYTICS",
    "CHEM_TRACEABILITY",
)


@router.get(
    "/dashboard",
    response_model=ChemDashboardOut,
    summary="Production dashboard KPIs, reactor status, and batch process flow",
)
def chem_dashboard(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_CHEM_READ),
):
    return chem_adapter.get_dashboard_summary(db, tenant)


@router.get(
    "/reactor-parameter-definitions",
    summary="Reactor parameter catalog for batch readings",
)
def chem_reactor_parameter_definitions(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(_CHEM_READ),
):
    return chem_adapter.list_reactor_parameter_definitions(db, tenant)
