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

load_dotenv()


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
            os.getenv("AUTH_DEV_USER_ROLES", "MES_Admin")
        )
    )


settings = Settings()
