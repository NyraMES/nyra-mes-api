"""Verify nyra_mes_core connectivity and seed data.

Usage (from repo root, with venv active):
    python scripts/verify_mes_core_connection.py

Credentials (pick one):
  • MES_CORE_DB_SECRET_ID — RDS secret in AWS Secrets Manager (recommended on testbed)
  • MES_CORE_DB_PASSWORD — direct password in .env (local dev)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.core.config import settings
from app.core.mes_core_credentials import get_mes_core_db_credentials
from app.db.mes_core_database import get_mes_core_engine


def main() -> int:
    print("nyra_mes_core connection check")
    print(f"  enabled   : {settings.mes_core_enabled}")
    print(f"  host      : {settings.mes_core_db_host}")
    print(f"  database  : {settings.mes_core_db_name}")
    print(f"  user      : {settings.mes_core_db_user}")
    print(f"  secret_id : {settings.mes_core_db_secret_id or '(not set)'}")

    if not settings.mes_core_enabled:
        print("\nERROR: MES_CORE_ENABLED is not true in .env")
        return 1

    if not settings.mes_core_db_secret_id and not settings.mes_core_db_password:
        print(
            "\nERROR: Configure database credentials in .env:\n"
            "  • MES_CORE_DB_SECRET_ID=rds!db-…  (AWS Secrets Manager — testbed)\n"
            "  • or MES_CORE_DB_PASSWORD=…       (local dev)\n"
            "  RDS console → nyra-mes-core → Configuration → Manage credentials"
        )
        return 1

    try:
        creds = get_mes_core_db_credentials()
        print(f"  resolved  : {creds.user}@{creds.host}/{creds.name}")
    except Exception as exc:
        print(f"\nERROR: Could not resolve credentials — {exc}")
        return 1

    engine = get_mes_core_engine()
    if engine is None:
        print("\nERROR: Could not create mes_core engine")
        return 1

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            tenants = conn.execute(
                text(
                    "SELECT t.tenant_code, t.tenant_name, it.template_code "
                    "FROM core.tenant t "
                    "JOIN template.industry_template it "
                    "ON t.industry_template_id = it.industry_template_id "
                    "ORDER BY t.tenant_code"
                )
            ).fetchall()
            products = conn.execute(
                text(
                    "SELECT product_code, product_name FROM mst.product "
                    "WHERE tenant_id = (SELECT tenant_id FROM core.tenant WHERE tenant_code = :code)"
                ),
                {"code": settings.default_tenant_code},
            ).fetchall()
    except Exception as exc:
        print(f"\nERROR: Connection failed — {exc}")
        return 1

    print("\nOK: Connected to nyra_mes_core")
    print(f"\nTenants ({len(tenants)}):")
    for row in tenants:
        print(f"  - {row[0]} | {row[1]} | template={row[2]}")

    print(f"\nProducts for {settings.default_tenant_code} ({len(products)}):")
    for row in products:
        print(f"  - {row[0]} | {row[1]}")

    print("\nNext: start API and open http://127.0.0.1:8000/docs")
    print("  GET /api/context")
    print("  GET /api/products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
