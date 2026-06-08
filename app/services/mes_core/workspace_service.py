"""Workspace (project/plant) services — core platform."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import ProjectWorkspace
from app.schemas.mes_core.schemas import ProjectWorkspaceOut


def list_workspaces(db: Session, tenant: TenantContext) -> List[ProjectWorkspaceOut]:
    rows = (
        db.query(ProjectWorkspace)
        .filter(ProjectWorkspace.tenant_id == tenant.tenant_id)
        .order_by(ProjectWorkspace.workspace_code)
        .all()
    )
    return [ProjectWorkspaceOut.model_validate(r) for r in rows]


def get_active_workspace(db: Session, tenant: TenantContext) -> Optional[ProjectWorkspaceOut]:
    if tenant.workspace_id:
        row = (
            db.query(ProjectWorkspace)
            .filter(
                ProjectWorkspace.tenant_id == tenant.tenant_id,
                ProjectWorkspace.workspace_id == tenant.workspace_id,
            )
            .first()
        )
        if row:
            return ProjectWorkspaceOut.model_validate(row)

    row = (
        db.query(ProjectWorkspace)
        .filter(
            ProjectWorkspace.tenant_id == tenant.tenant_id,
            ProjectWorkspace.status == "ACTIVE",
        )
        .order_by(ProjectWorkspace.workspace_code)
        .first()
    )
    return ProjectWorkspaceOut.model_validate(row) if row else None


def get_workspace_by_code(
    db: Session, tenant: TenantContext, workspace_code: str
) -> ProjectWorkspaceOut:
    row = (
        db.query(ProjectWorkspace)
        .filter(
            ProjectWorkspace.tenant_id == tenant.tenant_id,
            ProjectWorkspace.workspace_code == workspace_code,
        )
        .first()
    )
    if not row:
        raise NotFoundError(
            f"Workspace '{workspace_code}' not found for tenant '{tenant.tenant_code}'"
        )
    return ProjectWorkspaceOut.model_validate(row)
