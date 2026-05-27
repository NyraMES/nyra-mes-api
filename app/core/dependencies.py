"""Shared FastAPI dependencies.

Centralising dependency providers (e.g. database session) keeps route
modules small and lets services / utilities reach the same DI surface.
"""

from app.core.auth import (
    UserContext,
    get_current_user,
    require_roles,
    require_router_access,
)
from app.db.database import get_db

__all__ = [
    "UserContext",
    "get_current_user",
    "get_db",
    "require_roles",
    "require_router_access",
]