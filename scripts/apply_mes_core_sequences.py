"""Apply core.*_code_seq sequences to an existing nyra_mes_core database."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.db.mes_core_database import get_mes_core_engine

SEQUENCES = [
    "core.supplier_code_seq",
    "core.customer_code_seq",
    "core.product_code_seq",
    "core.resource_code_seq",
    "core.equipment_code_seq",
    "core.routing_code_seq",
    "core.routing_operation_code_seq",
    "core.customer_order_code_seq",
    "core.customer_order_line_code_seq",
    "core.production_order_code_seq",
    "core.lot_code_seq",
    "core.feasibility_check_code_seq",
    "core.execution_code_seq",
    "core.schedule_code_seq",
    "core.quality_check_code_seq",
    "core.ncr_code_seq",
    "core.dispatch_code_seq",
]


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("MES_CORE not configured")
        return 1
    with engine.begin() as conn:
        for seq in SEQUENCES:
            conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1"))
        rows = conn.execute(
            text(
                "SELECT sequencename FROM pg_sequences "
                "WHERE schemaname = 'core' ORDER BY 1"
            )
        ).fetchall()
    print("Applied sequences:", [r[0] for r in rows])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
