"""Link existing GR Carbons Cognito test logins into the Users screen directory.

Does not create or reset Cognito accounts.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.core.tenant_context import resolve_tenant  # noqa: E402
from app.db.mes_core_database import get_mes_core_engine  # noqa: E402
from app.services.industry.activated_carbon.users import (  # noqa: E402
    GR_CARBONS_TEST_USERS,
    ensure_known_directory_users,
)


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("MES_CORE is not enabled")
        return 1
    db = Session(bind=engine)
    try:
        tenant = resolve_tenant(db, "GR_CARBONS", "GR_CARBONS_ACTIVATED_CARBON")
        rows = ensure_known_directory_users(db, tenant, GR_CARBONS_TEST_USERS)
        print(f"Linked {len(rows)} GR Carbons test users (directory only, Cognito unchanged)")
        for row in rows:
            print(f"  {row['username']:28} {row['role_label']:18} {row['email']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
