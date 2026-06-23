"""One-off: list SAM_CARBONS tenants and order counts on mes core DB."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env.production", override=True)
if not os.getenv("MES_CORE_DB_HOST"):
    load_dotenv(ROOT / ".env", override=True)

from sqlalchemy import text
from app.db.mes_core_database import get_mes_core_engine

engine = get_mes_core_engine()
if engine is None:
    raise SystemExit("MES_CORE not enabled")

with engine.connect() as conn:
    tenants = conn.execute(
        text(
            "SELECT tenant_code, tenant_id FROM core.tenant "
            "WHERE tenant_code LIKE 'SAM_CARBONS%' ORDER BY tenant_code"
        )
    ).fetchall()
    print("Tenants on RDS:")
    for code, tid in tenants:
        orders = conn.execute(
            text(
                "SELECT COUNT(*) FROM trn.customer_order WHERE tenant_id = :tid"
            ),
            {"tid": str(tid)},
        ).scalar()
        customers = conn.execute(
            text("SELECT COUNT(*) FROM mst.customer WHERE tenant_id = :tid"),
            {"tid": str(tid)},
        ).scalar()
        products = conn.execute(
            text("SELECT COUNT(*) FROM mst.product WHERE tenant_id = :tid"),
            {"tid": str(tid)},
        ).scalar()
        resources = conn.execute(
            text("SELECT COUNT(*) FROM mst.resource WHERE tenant_id = :tid"),
            {"tid": str(tid)},
        ).scalar()
        print(
            f"  {code}: customers={customers}, products={products}, "
            f"resources={resources}, orders={orders}"
        )
        if int(orders or 0) > 0:
            sample = conn.execute(
                text(
                    "SELECT order_code FROM trn.customer_order "
                    "WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 3"
                ),
                {"tid": str(tid)},
            ).fetchall()
            print(f"    latest orders: {[r[0] for r in sample]}")

    print("\nPostgreSQL sequence values (next nextval):")
    seqs = [
        "core.customer_order_code_seq",
        "core.customer_order_line_code_seq",
        "core.production_order_code_seq",
        "core.lot_code_seq",
        "core.feasibility_check_code_seq",
    ]
    for seq in seqs:
        last = conn.execute(text(f"SELECT last_value, is_called FROM {seq}")).fetchone()
        print(f"  {seq}: last_value={last[0]}, is_called={last[1]}")
