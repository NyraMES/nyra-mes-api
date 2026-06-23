"""Tests for MES_SuperAdmin vs MES_Admin master-data permissions."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.auth import (
    MES_ADMIN,
    MES_PLANNER,
    MES_SUPER_ADMIN,
    UserContext,
    require_super_admin,
    require_tenant_admin,
)
from app.core.config import settings
from app.core.exceptions import ForbiddenError


def _user(*groups: str) -> UserContext:
    return UserContext(sub="1", username="u", groups=list(groups))


def test_super_admin_is_super_admin():
    user = _user(MES_SUPER_ADMIN)
    assert user.is_super_admin()
    assert user.is_tenant_admin()


def test_admin_is_tenant_admin_not_super():
    user = _user(MES_ADMIN)
    assert not user.is_super_admin()
    assert user.is_tenant_admin()


def test_planner_has_neither_admin_privilege():
    user = _user(MES_PLANNER)
    assert not user.is_super_admin()
    assert not user.is_tenant_admin()


def test_require_super_admin_blocks_admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    dep = require_super_admin().dependency
    with pytest.raises(ForbiddenError) as exc:
        dep(_user(MES_ADMIN))
    assert "Super Administrator" in exc.value.message


def test_require_super_admin_allows_super_admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    dep = require_super_admin().dependency
    assert dep(_user(MES_SUPER_ADMIN)) is not None


def test_require_tenant_admin_allows_admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    dep = require_tenant_admin().dependency
    assert dep(_user(MES_ADMIN)) is not None


def test_require_tenant_admin_blocks_planner(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    dep = require_tenant_admin().dependency
    with pytest.raises(ForbiddenError):
        dep(_user(MES_PLANNER))


def test_require_super_admin_skipped_when_auth_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=False)
    )
    dep = require_super_admin().dependency
    assert dep(_user(MES_PLANNER)) is not None
