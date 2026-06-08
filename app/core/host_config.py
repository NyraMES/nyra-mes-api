"""Hostname → tenant/workspace bindings for domain-scoped SPA deployments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from app.core.config import settings

# Built-in dev bindings; production client tenants come from HOST_TENANT_MAP env.
# ac.localhost is industry-only — tenant defaults to the generic AC demo tenant.
_AC_DEV_TENANT = "SAM_CARBONS_DEMO"
_AC_DEV_WORKSPACE = "SAM_CARBONS_DEMO_WS"

_BUILTIN_HOST_BINDINGS: Dict[str, Tuple[str, Optional[str], str]] = {
    "ac.localhost": (_AC_DEV_TENANT, _AC_DEV_WORKSPACE, "activated-carbon"),
    "oem.localhost": ("AUTO_OEM_DEMO", None, "automotive-oem"),
    "demo.localhost": ("NYRA_VIDEO_DEMO", None, "automotive-oem"),
}


@dataclass(frozen=True)
class HostBinding:
    host: str
    tenant_code: str
    workspace_code: Optional[str]
    industry_key: str

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "host": self.host,
            "tenant_code": self.tenant_code,
            "workspace_code": self.workspace_code,
            "industry_key": self.industry_key,
        }


def _normalize_host(host: str) -> str:
    value = (host or "").strip().lower()
    if ":" in value:
        value = value.split(":", 1)[0]
    return value


def _parse_host_tenant_map(raw: str) -> Dict[str, Tuple[str, Optional[str], str]]:
    """Parse ``host=tenant[:workspace][:industry]`` CSV from env."""
    parsed: Dict[str, Tuple[str, Optional[str], str]] = {}
    for entry in raw.split(","):
        item = entry.strip()
        if not item or "=" not in item:
            continue
        host_part, value_part = item.split("=", 1)
        host = _normalize_host(host_part)
        if not host:
            continue
        segments = [segment.strip() for segment in value_part.split(":") if segment.strip()]
        if not segments:
            continue
        tenant_code = segments[0]
        workspace_code = segments[1] if len(segments) > 1 else None
        industry_key = segments[2] if len(segments) > 2 else _industry_key_for_tenant(tenant_code)
        parsed[host] = (tenant_code, workspace_code, industry_key)
    return parsed


def _industry_key_for_tenant(tenant_code: str) -> str:
    """Infer industry only for known demo tenants — not client codes like SAM_CARBONS."""
    code = (tenant_code or "").upper()
    if code in (_AC_DEV_TENANT,):
        return "activated-carbon"
    if code in ("AUTO_OEM_DEMO", "NYRA_VIDEO_DEMO"):
        return "automotive-oem"
    return "generic"


def host_bindings() -> Dict[str, Tuple[str, Optional[str], str]]:
    merged = dict(_BUILTIN_HOST_BINDINGS)
    if settings.host_tenant_map:
        merged.update(_parse_host_tenant_map(settings.host_tenant_map))
    return merged


def resolve_host_binding(host: str) -> Optional[HostBinding]:
    normalized = _normalize_host(host)
    if not normalized:
        return None
    row = host_bindings().get(normalized)
    if not row:
        return None
    tenant_code, workspace_code, industry_key = row
    return HostBinding(
        host=normalized,
        tenant_code=tenant_code,
        workspace_code=workspace_code,
        industry_key=industry_key,
    )
