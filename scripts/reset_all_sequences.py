"""Reset every core.* business-code sequence and verify state."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.tenant_context import resolve_tenant
from app.db.mes_core_database import get_mes_core_engine
from app.services.industry.activated_carbon.codes import (
    ALL_CORE_CODE_SEQUENCES,
    reset_ac_sequences_empty,
    sync_ac_sequences,
)


def show_sequences(db) -> None:
    rows = db.execute(
        text(
            """
            SELECT sequencename,
                   pg_sequence_last_value(format('%I.%I', schemaname, sequencename)::regclass) AS last_value
            FROM pg_sequences
            WHERE schemaname = 'core'
            ORDER BY sequencename
            """
        )
    ).fetchall()
    print("=== core sequences ===")
    for name, last_value in rows:
        print(f"  {name:35} last={last_value}")


def ensure_sequences_exist(db) -> None:
    for seq in ALL_CORE_CODE_SEQUENCES:
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1"))
    db.commit()


def reset_all_to_empty(db) -> None:
    reset_ac_sequences_empty(db)


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("ERROR: MES_CORE not configured")
        return 1

    Session = sessionmaker(bind=engine)
    with Session() as db:
        print("Before reset:")
        show_sequences(db)

        ensure_sequences_exist(db)
        reset_all_to_empty(db)

        tenant = resolve_tenant(
            db,
            "GR_CARBONS",
            "GR_CARBONS_ACTIVATED_CARBON",
        )
        sync_ac_sequences(db, tenant.tenant_id)

        print("\nAfter reset + sync from tenant data:")
        show_sequences(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
