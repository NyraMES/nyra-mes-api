from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from sqlalchemy import text
from app.db.mes_core_database import get_mes_core_engine

with get_mes_core_engine().connect() as c:
    rows = c.execute(
        text(
            """
            SELECT co.order_code, co.metadata, p.product_code
            FROM trn.customer_order co
            JOIN trn.customer_order_line col ON col.order_id = co.customer_order_id
            JOIN mst.product p ON p.product_id = col.product_id
            WHERE co.tenant_id = 'b2000000-0000-4000-8000-000000000010'
            ORDER BY co.created_at DESC
            LIMIT 10
            """
        )
    ).fetchall()
    for row in rows:
        print(row)
