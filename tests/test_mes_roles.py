"""Tests for MES_SuperAdmin vs MES_Admin master-data permissions."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.core.auth import (
    MES_ACTIVATION,
    MES_ADMIN,
    MES_MANAGER,
    MES_PLANNER,
    MES_POST_ACTIVATION,
    MES_QUALITY,
    MES_RMS,
    MES_SUPER_ADMIN,
    UserContext,
    require_nyra_services,
    require_plant_admin,
    require_roles,
    require_super_admin,
    require_tenant_admin,
)
from app.core.ac_privileges import (
    AC_ACTIVATION_RUN_ROLES,
    AC_POST_QC_ROLES,
    AC_RMS_ROLES,
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


def test_quality_cannot_run_activation_or_rms(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    with pytest.raises(ForbiddenError):
        require_roles(*AC_ACTIVATION_RUN_ROLES).dependency(_user(MES_QUALITY))
    with pytest.raises(ForbiddenError):
        require_roles(*AC_RMS_ROLES).dependency(_user(MES_QUALITY))


def test_quality_can_save_post_qc(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    dep = require_roles(*AC_POST_QC_ROLES).dependency
    assert dep(_user(MES_QUALITY)) is not None
    assert dep(_user(MES_POST_ACTIVATION)) is not None


def test_manager_can_run_shop_not_blocked(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = _user(MES_MANAGER)
    assert require_roles(*AC_RMS_ROLES).dependency(user) is not None
    assert require_roles(*AC_ACTIVATION_RUN_ROLES).dependency(user) is not None
    assert require_roles(*AC_POST_QC_ROLES).dependency(user) is not None


def test_rms_cannot_run_activation(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    with pytest.raises(ForbiddenError):
        require_roles(*AC_ACTIVATION_RUN_ROLES).dependency(_user(MES_RMS))
    with pytest.raises(ForbiddenError):
        require_roles(*AC_POST_QC_ROLES).dependency(_user(MES_ACTIVATION))


def test_admin_does_not_bypass_shop_roles(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    with pytest.raises(ForbiddenError):
        require_roles(*AC_ACTIVATION_RUN_ROLES).dependency(_user(MES_ADMIN))


def test_require_plant_admin_allows_admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    assert require_plant_admin().dependency(_user(MES_ADMIN)) is not None


def test_require_plant_admin_blocks_manager(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    with pytest.raises(ForbiddenError):
        require_plant_admin().dependency(_user(MES_MANAGER))


def test_require_plant_admin_allows_nyraservices(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = UserContext(sub="1", username="nyraservices@grcarbons", groups=[MES_SUPER_ADMIN])
    assert require_plant_admin().dependency(user) is not None


def test_require_nyra_services_allows_username(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    user = UserContext(sub="1", username="nyraservices@grcarbons", groups=[MES_ADMIN])
    assert require_nyra_services().dependency(user) is not None


def test_require_nyra_services_blocks_admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.auth.settings", replace(settings, auth_enabled=True)
    )
    with pytest.raises(ForbiddenError):
        require_nyra_services().dependency(_user(MES_ADMIN))
