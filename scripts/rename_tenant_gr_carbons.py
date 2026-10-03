"""Rename production AC client tenant SAM_CARBONS → GR_CARBONS (same tenant_id UUIDs)."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.db.mes_core_database import get_mes_core_engine  # noqa: E402

OLD_TENANT = "SAM_CARBONS"
NEW_TENANT = "GR_CARBONS"
OLD_WS = "SAM_CARBONS_ACTIVATED_CARBON"
NEW_WS = "GR_CARBONS_ACTIVATED_CARBON"


def _code(db: Session, tenant_code: str) -> str | None:
    row = db.execute(
        text("SELECT tenant_code FROM core.tenant WHERE tenant_code = :c"),
        {"c": tenant_code},
    ).fetchone()
    return str(row[0]) if row else None


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("ERROR: MES_CORE not enabled — set MES_CORE_ENABLED=true in .env", file=sys.stderr)
        return 1
    db = Session(bind=engine)
    try:
        has_old = _code(db, OLD_TENANT) is not None
        has_new = _code(db, NEW_TENANT) is not None

        if has_new and not has_old:
            print(f"OK: Tenant already {NEW_TENANT}")
        elif has_old and not has_new:
            db.execute(
                text(
                    "UPDATE core.tenant SET tenant_code = :new, tenant_name = :name "
                    "WHERE tenant_code = :old"
                ),
                {"new": NEW_TENANT, "name": "GR Carbons", "old": OLD_TENANT},
            )
            db.execute(
                text(
                    "UPDATE core.project_workspace SET workspace_code = :new, "
                    "workspace_name = :name WHERE workspace_code = :old"
                ),
                {
                    "new": NEW_WS,
                    "name": "GR Carbons — Activated Carbon",
                    "old": OLD_WS,
                },
            )
            db.commit()
            print(f"OK: Renamed {OLD_TENANT} -> {NEW_TENANT}, {OLD_WS} -> {NEW_WS}")
        elif has_old and has_new:
            print(
                f"WARN: Both {OLD_TENANT} and {NEW_TENANT} exist — manual merge required.",
                file=sys.stderr,
            )
            return 1
        else:
            print(
                f"WARN: Neither {OLD_TENANT} nor {NEW_TENANT} found — run migrations 003+004 first.",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
