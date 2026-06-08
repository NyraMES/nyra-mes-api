"""One-off: list SAM_CARBONS tenants and order counts on mes core DB."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env.production", override=True)

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
