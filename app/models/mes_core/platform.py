"""Platform tables in nyra_mes_core (core.* and template.* schemas)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.mes_core_base import MesCoreBase


class IndustryTemplate(MesCoreBase):
    __tablename__ = "industry_template"
    __table_args__ = {"schema": "template"}

    industry_template_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_code = Column(String(64), nullable=False, unique=True)
    template_name = Column(String(256), nullable=False)
    description = Column(Text)
    template_version = Column(String(32), nullable=False, default="1.0.0")
    is_active = Column(Boolean, nullable=False, default=True)
    module_code = Column(String(128))
    landing_page = Column(String(512))
    ui_module_name = Column(String(128))
    api_module_name = Column(String(128))
    icon_name = Column(String(64))
    dashboard_component = Column(String(128))
    display_order = Column(Integer, nullable=False, default=100)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Tenant(MesCoreBase):
    __tablename__ = "tenant"
    __table_args__ = {"schema": "core"}

    tenant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_code = Column(String(64), nullable=False, unique=True)
    tenant_name = Column(String(256), nullable=False)
    industry_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template.industry_template.industry_template_id"),
        nullable=False,
    )
    status = Column(String(32), nullable=False, default="ACTIVE")
    timezone = Column(String(64), nullable=False, default="UTC")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class ProjectWorkspace(MesCoreBase):
    __tablename__ = "project_workspace"
    __table_args__ = {"schema": "core"}

    workspace_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False)
    workspace_code = Column(String(64), nullable=False)
    workspace_name = Column(String(256), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE")
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class UserProjectAccess(MesCoreBase):
    __tablename__ = "user_project_access"
    __table_args__ = {"schema": "core"}

    access_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("core.app_user.user_id"), nullable=False)
    workspace_id = Column(
        UUID(as_uuid=True),
        ForeignKey("core.project_workspace.workspace_id"),
        nullable=False,
    )
    role_code = Column(String(64), nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    granted_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Capability(MesCoreBase):
    __tablename__ = "capability"
    __table_args__ = {"schema": "core"}

    capability_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_code = Column(String(128), nullable=False, unique=True)
    capability_name = Column(String(256), nullable=False)
    description = Column(Text)
    category = Column(String(64))
    is_active = Column(Boolean, nullable=False, default=True)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class IndustryCapability(MesCoreBase):
    __tablename__ = "industry_capability"
    __table_args__ = {"schema": "template"}

    industry_capability_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    industry_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template.industry_template.industry_template_id"),
        nullable=False,
    )
    capability_id = Column(
        UUID(as_uuid=True),
        ForeignKey("core.capability.capability_id"),
        nullable=False,
    )
    display_order = Column(Integer, nullable=False, default=100)
    is_required = Column(Boolean, nullable=False, default=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
