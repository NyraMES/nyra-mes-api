from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text

load_dotenv()
url = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
)
engine = create_engine(url)
with engine.connect() as conn:
    rows = conn.execute(
        text(
            """
            SELECT tc.table_schema, tc.table_name, tc.constraint_type, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema IN ('mst', 'trn')
              AND tc.table_name IN (
                'process_library', 'data_capture_template', 'data_capture_field',
                'routing_operation', 'operation_data_capture', 'operation_data_capture_value'
              )
            ORDER BY tc.table_schema, tc.table_name, tc.constraint_type, kcu.ordinal_position
            """
        )
    ).all()
    for r in rows:
        print(r)
