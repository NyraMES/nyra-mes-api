"""Tenant-scoped query helpers for nyra_mes_core services.

Legacy services (``app.services.*``) query the original DB without ``tenant_id``.
All nyra_mes_core services must use these helpers so every SELECT/INSERT/UPDATE/DELETE
is scoped to the active tenant (and workspace when provided).
"""

from __future__ import annotations

from typing import Any, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.tenant_context import TenantContext

T = TypeVar("T")


class TenantRepository:
    """Base repository enforcing tenant_id (and optional workspace_id) on all DB ops."""

    def __init__(self, db: Session, tenant: TenantContext) -> None:
        self.db = db
        self.tenant = tenant
        self.tenant_id: UUID = tenant.tenant_id
        self.workspace_id: Optional[UUID] = tenant.workspace_id

    def _apply_workspace_scope(self, query: Query, model: Type[T]) -> Query:
        if self.workspace_id is None or not hasattr(model, "workspace_id"):
            return query
        return query.filter(
            (model.workspace_id.is_(None)) | (model.workspace_id == self.workspace_id)
        )

    def query(self, model: Type[T]) -> Query:
        # nyra_mes_core: every SELECT must filter by tenant_id (+ workspace when set).
        q = self.db.query(model).filter(model.tenant_id == self.tenant_id)
        return self._apply_workspace_scope(q, model)

    def query_workspace_strict(self, model: Type[T]) -> Query:
        """Tenant + exact workspace scope (required for workspace route customization)."""
        if self.workspace_id is None:
            raise ValidationError("Workspace context is required for this operation")
        if not hasattr(model, "workspace_id"):
            return self.db.query(model).filter(model.tenant_id == self.tenant_id)
        return self.db.query(model).filter(
            model.tenant_id == self.tenant_id,
            model.workspace_id == self.workspace_id,
        )

    def get_by_pk(self, model: Type[T], pk_column: Any, pk_value: Any) -> T:
        row = self.query(model).filter(pk_column == pk_value).first()
        if not row:
            raise NotFoundError(f"{model.__tablename__} '{pk_value}' not found")
        return row

    def get_by_code(self, model: Type[T], code_column: Any, code_value: str) -> T:
        row = self.query(model).filter(code_column == code_value).first()
        if not row:
            raise NotFoundError(f"{model.__tablename__} '{code_value}' not found")
        return row

    def _stamp_row(self, row: T) -> T:
        row.tenant_id = self.tenant_id
        if self.workspace_id is not None and hasattr(row, "workspace_id"):
            row.workspace_id = self.workspace_id
        if hasattr(row, "metadata_"):
            meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
            meta.setdefault("industry_template_code", self.tenant.industry_template_code)
            if self.workspace_id is not None:
                meta.setdefault("workspace_code", self.tenant.workspace_code)
            row.metadata_ = meta
        return row

    def add(self, row: T) -> T:
        # nyra_mes_core: every INSERT must set tenant_id (+ workspace when applicable).
        self._stamp_row(row)
        self.db.add(row)
        return row

    def commit_refresh(self, row: T) -> T:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            orig = getattr(exc, "orig", None)
            pg_detail = str(getattr(orig, "pgerror", None) or orig or exc)
            message = "Record already exists or violates constraints"
            if "duplicate key" in pg_detail.lower():
                message = (
                    "Duplicate ID — the order code already exists. "
                    "Click Refresh, then save again."
                )
            raise ConflictError(message) from exc
        self.db.refresh(row)
        return row

    def update_fields(self, row: T, updates: dict[str, Any]) -> T:
        for key, value in updates.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        return self.commit_refresh(row)

    def delete_by_pk(self, model: Type[T], pk_column: Any, pk_value: Any) -> None:
        # nyra_mes_core: every DELETE must include tenant_id (+ workspace when set).
        filters = [model.tenant_id == self.tenant_id, pk_column == pk_value]
        if self.workspace_id is not None and hasattr(model, "workspace_id"):
            filters.append(
                (model.workspace_id.is_(None)) | (model.workspace_id == self.workspace_id)
            )
        deleted = (
            self.db.query(model)
            .filter(*filters)
            .delete(synchronize_session=False)
        )
        if not deleted:
            raise NotFoundError(f"{model.__tablename__} '{pk_value}' not found")
        self.db.commit()
