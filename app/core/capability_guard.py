"""Capability-based authorization for industry-specific API routes."""

from __future__ import annotations

from typing import Callable

from fastapi import Depends

from app.core.exceptions import ForbiddenError
from app.core.tenant_context import TenantContext, get_tenant_context


def require_capability(capability_code: str) -> Callable:
    """FastAPI dependency factory — enforces an enabled industry capability."""

    def _guard(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if capability_code not in ctx.enabled_capabilities:
            raise ForbiddenError(
                f"Capability '{capability_code}' is not enabled for this tenant/template",
                details={
                    "capability_code": capability_code,
                    "industry_template_code": ctx.industry_template_code,
                    "enabled_capabilities": list(ctx.enabled_capabilities),
                },
            )
        return ctx

    return _guard


def require_any_capability(*capability_codes: str) -> Callable:
    """FastAPI dependency — passes if any listed capability is enabled."""

    def _guard(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if any(code in ctx.enabled_capabilities for code in capability_codes):
            return ctx
        raise ForbiddenError(
            f"None of capabilities {list(capability_codes)} are enabled for this workspace",
            details={
                "required_any": list(capability_codes),
                "industry_template_code": ctx.industry_template_code,
                "enabled_capabilities": list(ctx.enabled_capabilities),
            },
        )

    return _guard
