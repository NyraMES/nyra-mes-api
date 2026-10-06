"""Activated Carbon shop-floor privileges (per user role, per tenant).

Admin / Super Admin always pass via ``UserContext.has_any_role``.
"""

from __future__ import annotations

from app.core.auth import (
    MES_ACTIVATION,
    MES_MANAGER,
    MES_OPERATOR,
    MES_PLANNER,
    MES_POST_ACTIVATION,
    MES_QUALITY,
    MES_RMS,
    MES_VIEWER,
    require_roles,
)

# Manager is the plant-wide shop role. Planner is treated the same so existing
# Cognito planner users are not locked out of GR Carbons.
AC_MANAGER_ROLES = (MES_MANAGER, MES_PLANNER)

AC_RMS_ROLES = (MES_RMS, *AC_MANAGER_ROLES)
AC_ACTIVATION_RUN_ROLES = (MES_ACTIVATION, MES_OPERATOR, *AC_MANAGER_ROLES)
AC_POST_RUN_ROLES = (MES_POST_ACTIVATION, MES_OPERATOR, *AC_MANAGER_ROLES)
AC_ACTIVATION_QC_ROLES = (MES_ACTIVATION, MES_QUALITY, *AC_MANAGER_ROLES)
AC_POST_QC_ROLES = (MES_POST_ACTIVATION, MES_QUALITY, *AC_MANAGER_ROLES)
AC_QUALITY_ROLES = (MES_QUALITY, *AC_MANAGER_ROLES)
AC_REPORTS_ROLES = (*AC_MANAGER_ROLES, MES_VIEWER)
AC_DISPATCH_ROLES = AC_MANAGER_ROLES


def require_ac_rms():
    return require_roles(*AC_RMS_ROLES)


def require_ac_activation_run():
    return require_roles(*AC_ACTIVATION_RUN_ROLES)


def require_ac_post_run():
    return require_roles(*AC_POST_RUN_ROLES)


def require_ac_activation_qc():
    return require_roles(*AC_ACTIVATION_QC_ROLES)


def require_ac_post_qc():
    return require_roles(*AC_POST_QC_ROLES)


def require_ac_quality():
    return require_roles(*AC_QUALITY_ROLES)


def require_ac_reports():
    return require_roles(*AC_REPORTS_ROLES)


def require_ac_dispatch():
    return require_roles(*AC_DISPATCH_ROLES)
