"""One-off: release kiln schedule + optional FG stock for a completed lot."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.db.mes_core_database import get_mes_core_engine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lot_code", nargs="?", default="LOT-AC-2")
    parser.add_argument("--stock", action="store_true", help="Add lot qty to product fg_stock_kg")
    args = parser.parse_args()

    engine = get_mes_core_engine()
    now = datetime.now(timezone.utc).isoformat()

    with engine.begin() as conn:
        lot = conn.execute(
            text(
                "SELECT production_lot_id, lot_quantity, status, metadata "
                "FROM trn.production_lot WHERE lot_code = :code"
            ),
            {"code": args.lot_code},
        ).one_or_none()
        if not lot:
            print(f"Lot {args.lot_code} not found")
            return 1

        print(f"Before: status={lot.status}")

        execs = conn.execute(
            text(
                "SELECT execution_id, metadata FROM exec.operation_execution "
                "WHERE production_lot_id = :lid"
            ),
            {"lid": lot.production_lot_id},
        ).fetchall()

        for ex in execs:
            meta = dict(ex.metadata or {})
            meta["resources_released"] = True
            meta["resources_released_at"] = now
            meta.pop("planned_start_time", None)
            meta.pop("planned_end_time", None)
            meta["resources_claimed"] = []
            conn.execute(
                text(
                    "UPDATE exec.operation_execution SET metadata = CAST(:m AS jsonb) "
                    "WHERE execution_id = :eid"
                ),
                {"m": json.dumps(meta), "eid": ex.execution_id},
            )

        lot_meta = dict(lot.metadata or {})
        if args.stock:
            line = conn.execute(
                text(
                    "SELECT col.product_id, col.quantity "
                    "FROM trn.production_order po "
                    "JOIN trn.customer_order_line col ON col.order_line_id = po.order_line_id "
                    "JOIN trn.production_lot pl ON pl.production_order_id = po.production_order_id "
                    "WHERE pl.production_lot_id = :lid"
                ),
                {"lid": lot.production_lot_id},
            ).one_or_none()
            if line:
                prod = conn.execute(
                    text("SELECT metadata FROM mst.product WHERE product_id = :pid"),
                    {"pid": line.product_id},
                ).scalar()
                pm = dict(prod or {})
                qty = float(lot.lot_quantity or line.quantity or 0)
                current = float(pm.get("fg_stock_kg") or 0)
                pm["fg_stock_kg"] = str(current + qty)
                conn.execute(
                    text(
                        "UPDATE mst.product SET metadata = CAST(:m AS jsonb) "
                        "WHERE product_id = :pid"
                    ),
                    {"m": json.dumps(pm), "pid": line.product_id},
                )
                lot_meta["fg_stocked"] = True
                lot_meta["fg_stock_kg_added"] = str(qty)
                lot_meta["stocked_at"] = now
                lot_meta["qc_passed_at"] = now
                new_status = "STOCKED"
                print(f"Added {qty} kg to product FG stock (total {pm['fg_stock_kg']} kg)")
            else:
                new_status = "QC_PENDING"
        else:
            new_status = "QC_PENDING"
            lot_meta["routing_complete_at"] = now

        lot_meta["routing_complete_at"] = lot_meta.get("routing_complete_at") or now
        conn.execute(
            text(
                "UPDATE trn.production_lot SET status = :st, metadata = CAST(:m AS jsonb) "
                "WHERE production_lot_id = :lid"
            ),
            {"st": new_status, "m": json.dumps(lot_meta), "lid": lot.production_lot_id},
        )

        after = conn.execute(
            text("SELECT status, metadata FROM trn.production_lot WHERE production_lot_id = :lid"),
            {"lid": lot.production_lot_id},
        ).one()
        print(f"After: status={after.status}, fg_stocked={after.metadata.get('fg_stocked')}")
        print(f"Released schedule on {len(execs)} execution row(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
