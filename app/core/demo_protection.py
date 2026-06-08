"""Demo / prospect-safe guards — reduce API surface for video and shared demos."""

from __future__ import annotations

from typing import FrozenSet

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

_DEMO_WATERMARK = "Nyra Demo - Confidential - Fictional data only"

# Video-demo tenants inherit server DEMO_MODE / DEMO_READ_ONLY flags.
_DEMO_HARDENED_TENANT_CODES: FrozenSet[str] = frozenset({"NYRA_VIDEO_DEMO"})

# Local validation tenants — never inherit video-demo hardening.
_DEMO_EXEMPT_TENANT_CODES: FrozenSet[str] = frozenset({"SAM_CARBONS_DEMO", "SAM_CARBONS"})

# Mutations allowed in read-only demo (prospect-safe showcase).
_READ_ONLY_POST_ALLOW: FrozenSet[str] = frozenset(
    {
        "/api/ask",
    }
)

# Hidden in demo mode — exposes ontology / KG implementation detail.
_DEMO_BLOCKED_PREFIXES: tuple[str, ...] = (
    "/api/kg",
    "/ontology",
)


def demo_watermark_text() -> str:
    return _DEMO_WATERMARK


def _tenant_code_from_request(request: Request) -> str:
    return (
        request.headers.get("X-Tenant-Code")
        or request.headers.get("x-tenant-code")
        or request.query_params.get("tenant_code")
        or getattr(request.state, "tenant_code", None)
        or settings.default_tenant_code
        or ""
    ).strip()


def effective_demo_mode(tenant_code: str | None) -> bool:
    """True when this tenant should see demo-mode API behaviour."""
    code = (tenant_code or "").strip()
    if code in _DEMO_EXEMPT_TENANT_CODES:
        return False
    if code in _DEMO_HARDENED_TENANT_CODES:
        return settings.demo_mode
    return False


def effective_demo_read_only(tenant_code: str | None) -> bool:
    """True when this tenant should block write operations."""
    code = (tenant_code or "").strip()
    if code in _DEMO_EXEMPT_TENANT_CODES:
        return False
    if code in _DEMO_HARDENED_TENANT_CODES:
        return settings.demo_read_only
    return False


def is_demo_blocked_path(path: str) -> bool:
    normalized = (path or "").rstrip("/") or "/"
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}/")
        for prefix in _DEMO_BLOCKED_PREFIXES
    )


class DemoProtectionMiddleware(BaseHTTPMiddleware):
    """Strip sensitive routes and block writes when demo flags are enabled."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        tenant_code = _tenant_code_from_request(request)
        demo_mode = effective_demo_mode(tenant_code)
        demo_read_only = effective_demo_read_only(tenant_code)

        if demo_mode and is_demo_blocked_path(path):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not available in demo environment"},
            )

        if demo_read_only and request.method.upper() in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }:
            if path not in _READ_ONLY_POST_ALLOW and not path.startswith("/auth"):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Demo environment is read-only. "
                            "Contact Nyra for a full evaluation."
                        )
                    },
                )

        response = await call_next(request)

        if demo_mode:
            response.headers["X-Nyra-Demo"] = "true"
            response.headers["X-Nyra-Demo-Watermark"] = _DEMO_WATERMARK

        return response
