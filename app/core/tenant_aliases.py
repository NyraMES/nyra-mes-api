"""Canonical tenant/workspace codes after the SAM_CARBONS → GR_CARBONS rename.

Deployed UIs and Cognito users may still send the old codes. Resolve them to
the current plant so lookups do not 404.
"""

from __future__ import annotations

from typing import Optional

TENANT_CODE_ALIASES = {
    "SAM_CARBONS": "GR_CARBONS",
}

WORKSPACE_CODE_ALIASES = {
    "SAM_CARBONS_ACTIVATED_CARBON": "GR_CARBONS_ACTIVATED_CARBON",
}


def canonical_tenant_code(tenant_code: Optional[str]) -> Optional[str]:
    code = (tenant_code or "").strip()
    if not code:
        return tenant_code
    return TENANT_CODE_ALIASES.get(code, code)


def canonical_workspace_code(workspace_code: Optional[str]) -> Optional[str]:
    code = (workspace_code or "").strip()
    if not code:
        return workspace_code
    return WORKSPACE_CODE_ALIASES.get(code, code)
