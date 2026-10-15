"""Tenant + workspace + template context for nyra_mes_core multi-tenant requests.

Legacy routes do not use this module — they operate on the original DB without
tenant scoping.  New ``/api/*`` routes resolve context from:

  1. ``X-Tenant-Code`` header (or ``tenant_code`` query param)
  2. ``X-Workspace-Code`` header (or ``workspace_code`` query param)
  3. ``DEFAULT_TENANT_CODE`` env (``AUTO_OEM_DEMO`` when headers omitted)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth import UserContext, assert_user_may_access_tenant, get_current_user
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.tenant_aliases import canonical_tenant_code, canonical_workspace_code
from app.db.mes_core_database import get_mes_core_db
from app.models.mes_core.platform import (
    Capability,
    IndustryCapability,
    IndustryTemplate,
    ProjectWorkspace,
    Tenant,
)


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    tenant_code: str
    tenant_name: str
    workspace_id: Optional[UUID]
    workspace_code: Optional[str]
    workspace_name: Optional[str]
    industry_template_id: UUID
    industry_template_code: str
    industry_template_name: str
    module_code: Optional[str]
    landing_page: Optional[str]
    ui_module_name: Optional[str]
    api_module_name: Optional[str]
    icon_name: Optional[str]
    dashboard_component: Optional[str]
    enabled_capabilities: Tuple[str, ...]
    timezone: str = "UTC"

    def has_capability(self, capability_code: str) -> bool:
        return capability_code in self.enabled_capabilities


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Attach tenant/workspace codes to ``request.state`` before route handlers run."""

    async def dispatch(self, request: Request, call_next):
        tenant_code = (
            request.headers.get("X-Tenant-Code")
            or request.headers.get("x-tenant-code")
            or request.query_params.get("tenant_code")
            or settings.default_tenant_code
        ).strip()
        workspace_code = (
            request.headers.get("X-Workspace-Code")
            or request.headers.get("x-workspace-code")
            or request.query_params.get("workspace_code")
            or ""
        ).strip()
        request.state.tenant_code = canonical_tenant_code(tenant_code) or tenant_code
        request.state.workspace_code = canonical_workspace_code(workspace_code or None)
        return await call_next(request)


def _load_enabled_capabilities(db: Session, template_id: UUID) -> Tuple[str, ...]:
    try:
        rows = (
            db.query(Capability.capability_code)
            .join(IndustryCapability, IndustryCapability.capability_id == Capability.capability_id)
            .filter(
                IndustryCapability.industry_template_id == template_id,
                Capability.is_active.is_(True),
            )
            .order_by(IndustryCapability.display_order, Capability.capability_code)
            .all()
        )
        return tuple(code for (code,) in rows)
    except (ProgrammingError, OperationalError):
        db.rollback()
        return ()


def resolve_tenant(db: Session, tenant_code: str, workspace_code: Optional[str] = None) -> TenantContext:
    """Load tenant, workspace, industry template metadata, and enabled capabilities."""
    tenant_code = canonical_tenant_code(tenant_code) or tenant_code
    workspace_code = canonical_workspace_code(workspace_code)
    row = (
        db.query(Tenant, IndustryTemplate)
        .join(
            IndustryTemplate,
            Tenant.industry_template_id == IndustryTemplate.industry_template_id,
        )
        .filter(Tenant.tenant_code == tenant_code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Tenant '{tenant_code}' not found")
    tenant, template = row

    workspace: Optional[ProjectWorkspace] = None
    if workspace_code:
        workspace = (
            db.query(ProjectWorkspace)
            .filter(
                ProjectWorkspace.tenant_id == tenant.tenant_id,
                ProjectWorkspace.workspace_code == workspace_code,
            )
            .first()
        )
        if not workspace:
            raise NotFoundError(
                f"Workspace '{workspace_code}' not found for tenant '{tenant_code}'"
            )
    else:
        active_workspaces = (
            db.query(ProjectWorkspace)
            .filter(
                ProjectWorkspace.tenant_id == tenant.tenant_id,
                ProjectWorkspace.status == "ACTIVE",
            )
            .order_by(ProjectWorkspace.workspace_code)
            .all()
        )
        if len(active_workspaces) == 1:
            workspace = active_workspaces[0]

    enabled = _load_enabled_capabilities(db, template.industry_template_id)

    return TenantContext(
        tenant_id=tenant.tenant_id,
        tenant_code=tenant.tenant_code,
        tenant_name=tenant.tenant_name,
        workspace_id=workspace.workspace_id if workspace else None,
        workspace_code=workspace.workspace_code if workspace else None,
        workspace_name=workspace.workspace_name if workspace else None,
        industry_template_id=template.industry_template_id,
        industry_template_code=template.template_code,
        industry_template_name=template.template_name,
        module_code=template.module_code,
        landing_page=template.landing_page,
        ui_module_name=template.ui_module_name,
        api_module_name=template.api_module_name,
        icon_name=template.icon_name,
        dashboard_component=template.dashboard_component,
        enabled_capabilities=enabled,
        timezone=(tenant.timezone or "UTC").strip() or "UTC",
    )


def get_tenant_context(
    request: Request,
    db: Session = Depends(get_mes_core_db),
    user: UserContext = Depends(get_current_user),
) -> TenantContext:
    """FastAPI dependency — full request context for nyra_mes_core services."""
    cached: Optional[TenantContext] = getattr(request.state, "tenant_context", None)
    if cached is not None:
        return cached
    tenant_code = getattr(request.state, "tenant_code", settings.default_tenant_code)
    workspace_code = getattr(request.state, "workspace_code", None)
    assert_user_may_access_tenant(user, tenant_code)
    ctx = resolve_tenant(db, tenant_code, workspace_code)
    request.state.tenant_context = ctx
    return ctx
