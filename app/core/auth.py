"""AWS Cognito JWT validation and MES role checks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import ForbiddenError, UnauthorizedError

_bearer = HTTPBearer(auto_error=False)

# Cognito groups mapped to MES application roles.
MES_ADMIN = "MES_Admin"
MES_PLANNER = "MES_Planner"
MES_OPERATOR = "MES_Operator"
MES_QUALITY = "MES_Quality"
MES_VIEWER = "MES_Viewer"

ALL_MES_ROLES: Set[str] = {
    MES_ADMIN,
    MES_PLANNER,
    MES_OPERATOR,
    MES_QUALITY,
    MES_VIEWER,
}

# Which Cognito groups may access each API domain router.
ROUTER_ACCESS: Dict[str, Set[str]] = {
    "customer": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "part": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "order": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "production": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "lot": {MES_ADMIN, MES_PLANNER, MES_OPERATOR, MES_VIEWER},
    "routing": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "resource": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "feasibility": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "schedule": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "workorder": {MES_ADMIN, MES_PLANNER, MES_OPERATOR, MES_VIEWER},
    "process": {MES_ADMIN, MES_PLANNER, MES_VIEWER},
    "data_capture": {MES_ADMIN, MES_PLANNER, MES_OPERATOR, MES_VIEWER},
    "inspection": {MES_ADMIN, MES_QUALITY, MES_VIEWER},
    "ncr": {MES_ADMIN, MES_QUALITY, MES_VIEWER},
    "dispatch": {MES_ADMIN, MES_PLANNER, MES_QUALITY, MES_VIEWER},
    "traceability": ALL_MES_ROLES,
    "oee": ALL_MES_ROLES,
    "maintenance": {MES_ADMIN, MES_PLANNER, MES_OPERATOR, MES_VIEWER},
    "dashboard": ALL_MES_ROLES,
    "ontology": ALL_MES_ROLES,
    "auth": ALL_MES_ROLES,
    # Generic multi-tenant nyra_mes_core routes under /api/*
    "mes_core": ALL_MES_ROLES,
}

_jwks_cache: Dict[str, Any] = {"keys": None, "fetched_at": 0.0}


def _tenant_code_from_claims(claims: Dict[str, Any]) -> Optional[str]:
    """Cognito custom attribute ``custom:tenant_code`` scopes users to one tenant."""
    for key in ("custom:tenant_code", "tenant_code"):
        value = claims.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def assert_user_may_access_tenant(user: UserContext, tenant_code: str) -> None:
    """Phase-2 guard: JWT tenant must match the resolved request tenant."""
    if not settings.auth_enabled:
        return
    expected = (user.tenant_code or "").strip()
    requested = (tenant_code or "").strip()
    if not expected:
        raise ForbiddenError(
            "Your account is not assigned to a tenant. Contact your administrator.",
            details={"requested_tenant": requested},
        )
    if expected != requested:
        raise ForbiddenError(
            "This account belongs to a different plant. Sign in on the correct domain.",
            details={
                "your_tenant": expected,
                "requested_tenant": requested,
            },
        )


@dataclass(frozen=True)
class UserContext:
    sub: str
    username: str
    email: Optional[str] = None
    tenant_code: Optional[str] = None
    groups: List[str] = field(default_factory=list)

    @property
    def roles(self) -> List[str]:
        known = [g for g in self.groups if g in ALL_MES_ROLES]
        if known:
            return known
        return list(self.groups)

    def has_any_role(self, allowed: Set[str]) -> bool:
        if MES_ADMIN in self.groups:
            return True
        return bool(set(self.groups) & allowed)


def _cognito_issuer() -> str:
    return (
        f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/"
        f"{settings.cognito_user_pool_id}"
    )


def _fetch_jwks() -> Dict[str, Any]:
    now = time.time()
    if _jwks_cache["keys"] and now - _jwks_cache["fetched_at"] < 3600:
        return _jwks_cache["keys"]
    url = f"{_cognito_issuer()}/.well-known/jwks.json"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    _jwks_cache["keys"] = data
    _jwks_cache["fetched_at"] = now
    return data


def _rsa_key_for_token(token: str) -> Dict[str, str]:
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    if not kid:
        raise UnauthorizedError("Token missing key id")
    jwks = _fetch_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    _jwks_cache["keys"] = None
    jwks = _fetch_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise UnauthorizedError("Unable to find matching Cognito signing key")


def _validate_audience(claims: Dict[str, Any]) -> None:
    token_use = claims.get("token_use")
    client_id = settings.cognito_app_client_id
    if token_use == "access":
        if claims.get("client_id") != client_id:
            raise UnauthorizedError("Invalid access token client")
    elif token_use == "id":
        aud = claims.get("aud")
        if aud != client_id:
            raise UnauthorizedError("Invalid ID token audience")
    else:
        raise UnauthorizedError("Unsupported token type")


def decode_cognito_token(token: str) -> UserContext:
    if not settings.cognito_user_pool_id or not settings.cognito_app_client_id:
        raise UnauthorizedError("Cognito is not configured on the API")
    try:
        key = _rsa_key_for_token(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=_cognito_issuer(),
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise UnauthorizedError(f"Invalid token: {exc}") from exc

    _validate_audience(claims)

    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]

    username = (
        claims.get("cognito:username")
        or claims.get("username")
        or claims.get("email")
        or claims.get("sub")
        or "user"
    )
    return UserContext(
        sub=str(claims.get("sub") or username),
        username=str(username),
        email=claims.get("email"),
        tenant_code=_tenant_code_from_claims(claims),
        groups=[str(g) for g in groups],
    )


def _dev_user() -> UserContext:
    tenant = (settings.auth_dev_user_tenant_code or "").strip() or None
    return UserContext(
        sub="dev-user",
        username="dev",
        email=settings.auth_dev_user_email,
        tenant_code=tenant,
        groups=list(settings.auth_dev_user_roles),
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> UserContext:
    if not settings.auth_enabled:
        return _dev_user()

    if not credentials or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Missing bearer token")

    return decode_cognito_token(credentials.credentials)


def require_router_access(domain: str):
    allowed = ROUTER_ACCESS.get(domain, ALL_MES_ROLES)

    def _dependency(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not settings.auth_enabled:
            return user
        if not user.has_any_role(allowed):
            raise ForbiddenError(
                "You do not have permission to access this resource",
                details={"required_roles": sorted(allowed), "your_roles": user.roles},
            )
        return user

    return Depends(_dependency)


def require_roles(*roles: str):
    allowed = set(roles)

    def _dependency(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not settings.auth_enabled:
            return user
        if not user.has_any_role(allowed):
            raise ForbiddenError(
                "You do not have permission to perform this action",
                details={"required_roles": sorted(allowed), "your_roles": user.roles},
            )
        return user

    return Depends(_dependency)
