"""Activated Carbon shop-floor privileges (per user role, per tenant).

Admin / Super Admin always pass via ``UserContext.has_any_role``.
"""

from __future__ import annotations

from app.core.exceptions import ForbiddenError
from app.core.auth import (
    MES_ACTIVATION,
    MES_ADMIN,
    MES_MANAGER,
    MES_OPERATOR,
    MES_PLANNER,
    MES_POST_ACTIVATION,
    MES_QUALITY,
    MES_RMS,
    MES_SECURITY,
    MES_VIEWER,
    require_roles,
)

# Manager is the plant-wide shop role. Planner is treated the same so existing
# Cognito planner users are not locked out of GR Carbons.
AC_MANAGER_ROLES = (MES_MANAGER, MES_PLANNER)

AC_RMS_ROLES = (MES_RMS, *AC_MANAGER_ROLES)
AC_GATE_RECEIPT_ROLES = (MES_SECURITY, MES_ADMIN, *AC_MANAGER_ROLES)
AC_ACTIVATION_RUN_ROLES = (MES_ACTIVATION, MES_OPERATOR, *AC_MANAGER_ROLES)
AC_POST_RUN_ROLES = (MES_POST_ACTIVATION, MES_OPERATOR, *AC_MANAGER_ROLES)
AC_ACTIVATION_QC_ROLES = (MES_QUALITY, *AC_MANAGER_ROLES)
AC_POST_QC_ROLES = (MES_QUALITY, *AC_MANAGER_ROLES)
AC_QUALITY_ROLES = (MES_QUALITY, *AC_MANAGER_ROLES)
AC_REPORTS_ROLES = (*AC_MANAGER_ROLES, MES_VIEWER)
AC_DISPATCH_ROLES = AC_MANAGER_ROLES


def require_ac_rms():
    return require_roles(*AC_RMS_ROLES)


def assert_rms_engineer_records_bags(user) -> None:
    """Ungraded bag generation (IN-RMS-BAG) is the RMS engineer on Inbound prep.

    Nyra and super admin still pass. A supervisor login does not.
    """
    if user is None or not user.has_any_role({MES_RMS}):
        raise ForbiddenError("Bag generation is recorded by the RMS engineer on Inbound prep.")


def assert_supervisor_raises_debit_note(user) -> None:
    """A debit note is raised by the supervisor (manager, planner, or plant admin)."""
    if user is None or not user.has_any_role({MES_ADMIN, *AC_MANAGER_ROLES}):
        raise ForbiddenError("A debit note is raised by the supervisor.")


def assert_quality_records_lab(user) -> None:
    """Raw-material Lab (IN-LAB) is a quality check. Only Quality records it.

    Nyra and super admin still pass. RMS and the supervisor do not.
    """
    if user is None or not user.has_any_role({MES_QUALITY}):
        raise ForbiddenError("Lab is a quality check and is recorded by Quality.")


def assert_rms_engineer_records_outward(user) -> None:
    """RMS outward (IN-RM-OUT) is recorded by the RMS engineer after Lab."""
    if user is None or not user.has_any_role({MES_RMS}):
        raise ForbiddenError("RMS outward is recorded by the RMS engineer.")


def assert_can_complete_inbound_step(user, operation_code: str | None) -> None:
    """Keep each inbound code. Lab is Quality. Bag generation and RMS outward are the RMS engineer."""
    code = (operation_code or "").strip().upper()
    if code == "IN-LAB":
        assert_quality_records_lab(user)
        return
    if code == "IN-RMS-BAG":
        assert_rms_engineer_records_bags(user)
        return
    if code == "IN-RM-OUT":
        assert_rms_engineer_records_outward(user)
        return
    if user is None or not user.has_any_role(set(AC_RMS_ROLES)):
        raise ForbiddenError("This inbound step is recorded by the RMS engineer.")


def require_ac_gate_receipt():
    """Gate receipt: plant supervisor and security."""
    return require_roles(*AC_GATE_RECEIPT_ROLES)


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


def require_ac_destoning_ctc():
    """Plant supervisor, plant admin, or activation lead may set destoner CTC."""
    return require_roles(*AC_MANAGER_ROLES, MES_ADMIN, MES_ACTIVATION)


def user_can_see_supplier(user) -> bool:
    """Supplier name and code stay with the manager, planner, and plant admin."""
    if user is None:
        return False
    return user.has_any_role({MES_ADMIN, MES_SECURITY, *AC_MANAGER_ROLES})


def without_supplier_identity(row):
    """Drop supplier name, code, and id from an API row. Weights stay."""
    if row is None or not hasattr(row, "model_copy"):
        return row
    updates = {}
    fields = getattr(type(row), "model_fields", {})
    for field in ("supplier_id", "supplier_code", "supplier_name", "supplier_value_inr"):
        if field in fields:
            updates[field] = None
    note = getattr(row, "debit_note", None)
    if note is not None and hasattr(note, "model_copy"):
        updates["debit_note"] = note.model_copy(
            update={"supplier_code": None, "supplier_name": None}
        )
    suppliers = getattr(row, "suppliers", None)
    if isinstance(suppliers, list) and "suppliers" in fields:
        updates["suppliers"] = []
    message = getattr(row, "message", None)
    if isinstance(message, str) and "supplier" in message.lower():
        updates["message"] = None
    if not updates:
        return row
    return row.model_copy(update=updates)


def visible_supplier_row(user, row):
    if user_can_see_supplier(user):
        return row
    return without_supplier_identity(row)


def visible_supplier_rows(user, rows):
    if user_can_see_supplier(user):
        return rows
    return [without_supplier_identity(row) for row in rows]
