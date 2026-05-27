from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text

load_dotenv()
url = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)
engine = create_engine(url)
tables = [
    "mst.process_library",
    "mst.data_capture_template",
    "mst.data_capture_field",
    "mst.routing_operation",
    "trn.operation_data_capture",
    "trn.operation_data_capture_value",
]
with engine.connect() as conn:
    for full in tables:
        schema, name = full.split(".")
        rows = conn.execute(
            text(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :name
                ORDER BY ordinal_position
                """
            ),
            {"schema": schema, "name": name},
        ).all()
        print(f"=== {full} ===")
        if not rows:
            print("  (table not found)")
            continue
        for col, dtype, nullable in rows:
            print(f"  {col}: {dtype} nullable={nullable}")
