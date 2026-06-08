"""Auth endpoints for the SPA."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import UserContext, get_current_user
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.host_config import resolve_host_binding
from app.core.openapi_tags import Tags
from app.schemas.auth import AuthConfigOut, HostBindingOut, UserContextOut

router = APIRouter(tags=[Tags.AUTH])


@router.get(
    "/auth/config",
    response_model=AuthConfigOut,
    summary="Public auth configuration for the frontend",
)
def auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        auth_enabled=settings.auth_enabled,
        cognito_region=settings.cognito_region or None,
        cognito_user_pool_id=settings.cognito_user_pool_id or None,
        cognito_app_client_id=settings.cognito_app_client_id or None,
    )


@router.get(
    "/auth/me",
    response_model=UserContextOut,
    summary="Current authenticated user and roles",
)
def auth_me(user: UserContext = Depends(get_current_user)) -> UserContextOut:
    return UserContextOut(
        sub=user.sub,
        username=user.username,
        email=user.email,
        tenant_code=user.tenant_code,
        groups=user.groups,
        roles=user.roles,
    )


@router.get(
    "/auth/host-config",
    response_model=HostBindingOut,
    summary="Resolve tenant/workspace from request hostname",
)
def auth_host_config(host: str) -> HostBindingOut:
    binding = resolve_host_binding(host)
    if not binding:
        raise NotFoundError(f"No tenant binding for host '{host}'")
    return HostBindingOut(**binding.to_dict())
