"""Tests for tenant-scoped Cognito users and host bindings."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.auth import (
    UserContext,
    assert_user_may_access_tenant,
    _tenant_code_from_claims,
)
from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.core.host_config import resolve_host_binding


def test_tenant_code_from_claims_prefers_custom_attribute():
    claims = {"custom:tenant_code": "SAM_CARBONS", "tenant_code": "OTHER"}
    assert _tenant_code_from_claims(claims) == "SAM_CARBONS"


def test_assert_user_may_access_tenant_allows_match(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = UserContext(sub="1", username="u", tenant_code="SAM_CARBONS")
    assert_user_may_access_tenant(user, "SAM_CARBONS")


def test_assert_user_may_access_tenant_blocks_mismatch(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = UserContext(sub="1", username="u", tenant_code="SAM_CARBONS")
    with pytest.raises(ForbiddenError) as exc:
        assert_user_may_access_tenant(user, "AUTO_OEM_DEMO")
    assert "different plant" in exc.value.message


def test_assert_user_may_access_tenant_allows_ac_demo_playground(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = UserContext(
        sub="1",
        username="admin1",
        tenant_code="AUTO_OEM_DEMO",
        groups=["MES_Admin"],
    )
    assert_user_may_access_tenant(user, "SAM_CARBONS_DEMO")


def test_assert_user_may_access_tenant_blocks_missing_claim(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = UserContext(sub="1", username="u", tenant_code=None)
    with pytest.raises(ForbiddenError) as exc:
        assert_user_may_access_tenant(user, "SAM_CARBONS")
    assert "not assigned" in exc.value.message


def test_assert_user_may_access_tenant_skipped_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=False)
    )
    user = UserContext(sub="1", username="u", tenant_code=None)
    assert_user_may_access_tenant(user, "SAM_CARBONS")


def test_resolve_builtin_ac_localhost_binding():
    binding = resolve_host_binding("ac.localhost")
    assert binding is not None
    assert binding.tenant_code == "SAM_CARBONS_DEMO"
    assert binding.workspace_code == "SAM_CARBONS_DEMO_WS"
    assert binding.industry_key == "activated-carbon"


def test_resolve_host_binding_unknown_returns_none():
    assert resolve_host_binding("unknown.example.com") is None
