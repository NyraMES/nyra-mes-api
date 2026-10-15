"""Tenant/workspace-scoped kiln parameter catalog for Activated Carbon."""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core.platform import ProjectWorkspace
from app.schemas.mes_core.schemas import AcKilnParameterDefinition, AcKilnParameterDefinitionCreate
from app.services.industry.activated_carbon.constants import KILN_PARAMETER_DEFINITIONS
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _normalize_key(key: str) -> str:
    return (key or "").strip().lower().replace(" ", "_")


def is_scrap_kiln_parameter(key: str, label: str = "") -> bool:
    return "scrap" in f"{key} {label}".lower()


def without_scrap_parameters(definitions: List[AcKilnParameterDefinition]) -> List[AcKilnParameterDefinition]:
    return [row for row in definitions if not is_scrap_kiln_parameter(row.key, row.label or "")]


def list_kiln_parameter_definitions(
    db: Session, tenant: TenantContext
) -> List[AcKilnParameterDefinition]:
    if not tenant.workspace_id:
        return list(KILN_PARAMETER_DEFINITIONS)

    repo = _repo(db, tenant)
    ws = repo.get_by_pk(
        ProjectWorkspace, ProjectWorkspace.workspace_id, tenant.workspace_id
    )
    meta = ws.metadata_ if isinstance(ws.metadata_, dict) else {}
    raw = meta.get("kiln_parameter_definitions")
    if isinstance(raw, list) and raw:
        return without_scrap_parameters(
            [AcKilnParameterDefinition.model_validate(item) for item in raw]
        )
    return without_scrap_parameters(list(KILN_PARAMETER_DEFINITIONS))


def _persist_definitions(
    db: Session, tenant: TenantContext, definitions: List[AcKilnParameterDefinition]
) -> List[AcKilnParameterDefinition]:
    if not tenant.workspace_id:
        raise ValidationError("Workspace context is required to save kiln parameters")

    repo = _repo(db, tenant)
    ws = repo.get_by_pk(
        ProjectWorkspace, ProjectWorkspace.workspace_id, tenant.workspace_id
    )
    meta = dict(ws.metadata_ or {})
    meta["kiln_parameter_definitions"] = [d.model_dump() for d in definitions]
    ws.metadata_ = meta
    repo.commit_refresh(ws)
    return definitions


def add_kiln_parameter_definition(
    db: Session, tenant: TenantContext, payload: AcKilnParameterDefinitionCreate
) -> AcKilnParameterDefinition:
    key = _normalize_key(payload.key)
    if not key:
        raise ValidationError("Parameter key is required")
    label = (payload.label or "").strip()
    if not label:
        raise ValidationError("Parameter label is required")
    if is_scrap_kiln_parameter(key, label):
        raise ValidationError("Scrap is not a kiln parameter.")

    definitions = list_kiln_parameter_definitions(db, tenant)
    if any(d.key == key for d in definitions):
        raise ConflictError(f"Kiln parameter '{key}' already exists")

    row = AcKilnParameterDefinition(
        key=key,
        label=label,
        unit=(payload.unit or "").strip() or None,
    )
    definitions.append(row)
    _persist_definitions(db, tenant, definitions)
    return row
