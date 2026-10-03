"""Force-release all plant resources (kilns, machines, tools, labor) for a tenant.

Usage (from repo root, venv active):
    python scripts/release_all_plant_resources.py
    python scripts/release_all_plant_resources.py --tenant SAM_CARBONS
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
from app.services.industry.activated_carbon.resource_pool import (
    release_all_tenant_plant_resources,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="SAM_CARBONS")
    parser.add_argument("--workspace", default="SAM_CARBONS_ACTIVATED_CARBON")
    args = parser.parse_args()

    engine = get_mes_core_engine()
    Session = sessionmaker(bind=engine)
    with Session() as db:
        tenant = resolve_tenant(db, args.tenant, args.workspace)
        counts = release_all_tenant_plant_resources(db, tenant)

    print(f"Released plant resources for {args.tenant}:")
    print(f"  equipment rows reset : {counts['equipment']}")
    print(f"  resource rows reset  : {counts['resources']}")
    print(f"  kiln lot claims      : {counts['lots']}")
    print(f"  execution holds      : {counts['executions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
