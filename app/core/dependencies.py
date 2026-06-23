"""Shared FastAPI dependencies.

Centralising dependency providers (e.g. database session) keeps route
modules small and lets services / utilities reach the same DI surface.
"""

from app.core.auth import (
    UserContext,
    get_current_user,
    require_roles,
    require_router_access,
    require_super_admin,
    require_tenant_admin,
)
from app.core.capability_guard import require_capability
from app.core.tenant_context import TenantContext, get_tenant_context
from app.db.database import get_db
from app.db.mes_core_database import get_mes_core_db

__all__ = [
    "TenantContext",
    "UserContext",
    "get_current_user",
    "get_db",
    "get_mes_core_db",
    "get_tenant_context",
    "require_capability",
    "require_roles",
    "require_router_access",
    "require_super_admin",
    "require_tenant_admin",
]