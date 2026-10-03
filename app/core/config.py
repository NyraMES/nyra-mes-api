"""Application configuration.

Loaded once at import time from environment variables (``.env`` is read by
``app.db.database``). Keeping this in ``core`` lets services and tests
read settings without reaching into the routes layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

load_dotenv(override=True)
# Optional isolated demo env (see scripts/run_video_demo.ps1)
if os.getenv("NYRA_USE_DEMO_ENV", "").lower() in ("1", "true", "yes"):
    load_dotenv(".env.demo", override=True)


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    app_name: str = "Nyra MES API"
    app_version: str = "1.0.0"
    app_description: str = (
        "Manufacturing Workflow Intelligence Platform for "
        "Automobile OEM suppliers. Ontology-driven backend that orchestrates "
        "Customer Order -> Production Order -> Lot Split -> Routing -> "
        "Feasibility -> Scheduling -> Work Order -> Execution -> "
        "Inspection -> NCR -> Dispatch -> Traceability."
    )

    # CORS
    cors_allow_origins: List[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv(
                "CORS_ALLOW_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        )
    )

    # ID generation. Prefixes deliberately match the existing convention in
    # the production DB (CUST00001, PART00001, PROD00001, LOT00001, ...)
    # so new business codes stay consistent with what's already there.
    id_prefix_customer: str = "CUST"
    id_prefix_order: str = "ORD"
    id_prefix_order_line: str = "ORDL"
    id_prefix_production_order: str = "PROD"
    id_prefix_lot: str = "LOT"
    id_prefix_routing: str = "ROUTE"
    id_prefix_operation: str = "OP"
    id_prefix_schedule: str = "SCH"
    id_prefix_work_order: str = "WO"
    id_prefix_inspection_result: str = "INSP"
    id_prefix_ncr: str = "NCR"
    id_prefix_dispatch: str = "DSP"
    id_prefix_part: str = "PART"

    # Width for the numeric tail of generated IDs (CUST00001).
    id_pad_width: int = 5

    # Workflow gates
    feasibility_ready_status: str = "READY"

    # AWS Cognito (optional — set AUTH_ENABLED=true to enforce JWT + RBAC)
    auth_enabled: bool = field(
        default_factory=lambda: os.getenv("AUTH_ENABLED", "false").lower()
        in ("1", "true", "yes")
    )
    cognito_region: str = os.getenv("COGNITO_REGION", "us-east-1")
    cognito_user_pool_id: str = os.getenv("COGNITO_USER_POOL_ID", "")
    cognito_app_client_id: str = os.getenv("COGNITO_APP_CLIENT_ID", "")
    auth_dev_user_email: str = os.getenv("AUTH_DEV_USER_EMAIL", "dev@localhost")
    auth_dev_user_roles: List[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("AUTH_DEV_USER_ROLES", "MES_SuperAdmin")
        )
    )
    # Dev-only tenant scope when AUTH_ENABLED=false (mirrors Cognito custom:tenant_code).
    auth_dev_user_tenant_code: str = os.getenv("AUTH_DEV_USER_TENANT_CODE", "").strip()
    # host=tenant[:workspace][:industry] CSV for domain → tenant routing (see host_config.py).
    host_tenant_map: str = os.getenv("HOST_TENANT_MAP", "").strip()

    # Legacy oemauto DB — disabled by default; set LEGACY_DB_ENABLED=true to reconnect.
    legacy_db_enabled: bool = field(
        default_factory=lambda: os.getenv("LEGACY_DB_ENABLED", "false").lower()
        in ("1", "true", "yes")
    )
    legacy_db_host: str = os.getenv("DB_HOST", "").strip()
    legacy_db_port: str = os.getenv("DB_PORT", "5432").strip()
    legacy_db_name: str = os.getenv("DB_NAME", "").strip()
    legacy_db_user: str = os.getenv("DB_USER", "").strip()
    legacy_db_password: str = os.getenv("DB_PASSWORD", "")

    # nyra_mes_core — sole active database when LEGACY_DB_ENABLED=false.
    mes_core_enabled: bool = field(
        default_factory=lambda: os.getenv("MES_CORE_ENABLED", "false").lower()
        in ("1", "true", "yes")
    )
    mes_core_db_host: str = os.getenv("MES_CORE_DB_HOST", "").strip()
    mes_core_db_port: str = os.getenv("MES_CORE_DB_PORT", "5432").strip()
    mes_core_db_name: str = os.getenv("MES_CORE_DB_NAME", "nyra_mes_core")
    mes_core_db_user: str = os.getenv("MES_CORE_DB_USER", "").strip()
    mes_core_db_password: str = os.getenv("MES_CORE_DB_PASSWORD", "")
    # RDS Secrets Manager secret name or ARN (preferred on testbed; see mes_core_credentials.py).
    mes_core_db_secret_id: str = os.getenv("MES_CORE_DB_SECRET_ID", "").strip()
    mes_core_aws_region: str = os.getenv(
        "MES_CORE_AWS_REGION",
        os.getenv("AWS_REGION", os.getenv("COGNITO_REGION", "eu-north-1")),
    ).strip()
    # Until login resolves tenant from JWT, default to the demo tenant seed.
    default_tenant_code: str = os.getenv("DEFAULT_TENANT_CODE", "AUTO_OEM_DEMO")

    # Prospect / video demo hardening (see app.core.demo_protection)
    demo_mode: bool = field(
        default_factory=lambda: os.getenv("DEMO_MODE", "false").lower()
        in ("1", "true", "yes")
    )
    demo_read_only: bool = field(
        default_factory=lambda: os.getenv("DEMO_READ_ONLY", "false").lower()
        in ("1", "true", "yes")
    )
    # Testbed: allow SAM_CARBONS_DEMO JWT users to call SAM_CARBONS APIs (and vice versa).
    ac_demo_tenant_bridge: bool = field(
        default_factory=lambda: os.getenv("AC_DEMO_TENANT_BRIDGE", "false").lower()
        in ("1", "true", "yes")
    )

    # Landing-page contact form (POST /public/contact-enquiry — no mail client)
    contact_enquiry_enabled: bool = field(
        default_factory=lambda: os.getenv("CONTACT_ENQUIRY_ENABLED", "true").lower()
        in ("1", "true", "yes")
    )
    contact_to_email: str = os.getenv("CONTACT_TO_EMAIL", "sudhasankaran@nyraias.com").strip()
    contact_from_email: str = os.getenv(
        "CONTACT_FROM_EMAIL", "sudhasankaran@nyraias.com"
    ).strip()
    contact_aws_region: str = os.getenv(
        "CONTACT_AWS_REGION",
        os.getenv("AWS_REGION", os.getenv("COGNITO_REGION", "eu-north-1")),
    ).strip()
    contact_enquiry_dry_run: bool = field(
        default_factory=lambda: os.getenv("CONTACT_ENQUIRY_DRY_RUN", "false").lower()
        in ("1", "true", "yes")
    )


settings = Settings()
