"""Unit tests for tenant context and capability guards (no database required)."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.core.capability_guard import require_capability
from app.core.exceptions import ForbiddenError
from app.core.tenant_context import TenantContext


def _sample_context(*capabilities: str) -> TenantContext:
    return TenantContext(
        tenant_id=UUID("b2000000-0000-4000-8000-000000000001"),
        tenant_code="AUTO_OEM_DEMO",
        tenant_name="Automobile OEM Demo Tenant",
        workspace_id=None,
        workspace_code=None,
        workspace_name=None,
        industry_template_id=UUID("a1000000-0000-4000-8000-000000000001"),
        industry_template_code="AUTOMOBILE_OEM",
        industry_template_name="Automobile OEM Supplier",
        module_code="automotive-oem",
        landing_page="/automotive-oem/dashboard",
        ui_module_name="AutomotiveOemModule",
        api_module_name="automotiveOemApi",
        icon_name="car",
        dashboard_component="AutomotiveOemDashboard",
        enabled_capabilities=tuple(capabilities),
    )


def test_tenant_context_has_capability():
    ctx = _sample_context("AC_KILN_FEED")
    assert ctx.has_capability("AC_KILN_FEED")
    assert not ctx.has_capability("AC_TRACEABILITY")


def test_require_capability_allows_when_enabled():
    guard = require_capability("AC_KILN_FEED")
    ctx = _sample_context("AC_KILN_FEED")
    result = guard(ctx)
    assert result.tenant_code == "AUTO_OEM_DEMO"


def test_require_capability_blocks_when_missing():
    guard = require_capability("AC_KILN_FEED")
    ctx = _sample_context()
    with pytest.raises(ForbiddenError):
        guard(ctx)
