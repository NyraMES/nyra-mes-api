"""Quick row-count check for key MES tables."""
from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

url = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)

queries = [
    ("customers", "SELECT COUNT(*) FROM mst.customer"),
    ("parts", "SELECT COUNT(*) FROM mst.part"),
    ("orders", "SELECT COUNT(*) FROM trn.customer_order"),
    ("order_lines", "SELECT COUNT(*) FROM trn.order_line"),
    ("production_orders", "SELECT COUNT(*) FROM trn.production_order"),
    ("lots", "SELECT COUNT(*) FROM trn.production_lot"),
    ("machines", "SELECT COUNT(*) FROM mst.machine"),
    ("work_orders", "SELECT COUNT(*) FROM trn.work_order"),
]

engine = create_engine(url)
with engine.connect() as conn:
    for name, q in queries:
        try:
            count = conn.execute(text(q)).scalar()
            print(f"{name}: {count}")
        except Exception as exc:
            print(f"{name}: ERROR - {exc}")
