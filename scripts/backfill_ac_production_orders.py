"""Backfill production orders for raw material inward records missing a PO.

Usage (from repo root, venv active):
    python scripts/backfill_ac_production_orders.py
    python scripts/backfill_ac_production_orders.py --tenant SAM_CARBONS --workspace SAM_CARBONS_ACTIVATED_CARBON
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import sessionmaker

from app.core.tenant_context import resolve_tenant
from app.db.mes_core_database import get_mes_core_engine
from app.services.industry.activated_carbon import adapter as ac_adapter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="SAM_CARBONS")
    parser.add_argument("--workspace", default="SAM_CARBONS_ACTIVATED_CARBON")
    args = parser.parse_args()

    engine = get_mes_core_engine()
    Session = sessionmaker(bind=engine)
    with Session() as db:
        tenant = resolve_tenant(db, args.tenant, args.workspace)
        created = ac_adapter.backfill_inward_production_orders(db, tenant)

    if not created:
        print("OK: No inward orders needed a production order backfill.")
        return 0

    print(f"OK: Created {len(created)} production order(s):")
    for row in created:
        print(f"  {row['order_code']} -> {row['production_order_code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
