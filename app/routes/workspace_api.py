"""Project workspace routes — core platform."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_mes_core_db, get_tenant_context
from app.core.openapi_tags import Tags
from app.core.tenant_context import TenantContext
from app.schemas.mes_core.schemas import ProjectWorkspaceOut
from app.services.mes_core import workspace_service

router = APIRouter(prefix="/api/workspaces", tags=[Tags.WORKSPACE])


@router.get("", response_model=List[ProjectWorkspaceOut], summary="List workspaces for tenant")
def list_workspaces(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return workspace_service.list_workspaces(db, tenant)


@router.get(
    "/active",
    response_model=Optional[ProjectWorkspaceOut],
    summary="Active workspace from headers or first active workspace",
)
def get_active_workspace(
    db: Session = Depends(get_mes_core_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return workspace_service.get_active_workspace(db, tenant)
