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
            SELECT
              conrelid::regclass AS source_table,
              a.attname AS source_column,
              confrelid::regclass AS target_table,
              af.attname AS target_column
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attnum = ANY(c.conkey) AND a.attrelid = c.conrelid
            JOIN pg_attribute af ON af.attnum = ANY(c.confkey) AND af.attrelid = c.confrelid
            WHERE c.contype = 'f'
              AND conrelid::regclass::text LIKE ANY(ARRAY[
                'mst.data_capture_%', 'mst.routing_operation', 'trn.operation_data_capture%'
              ])
            ORDER BY 1, 2
            """
        )
    ).all()
    for r in rows:
        print(r)

    print("\n--- sample counts ---")
    for q in [
        "SELECT COUNT(*) FROM mst.process_library",
        "SELECT COUNT(*) FROM mst.data_capture_template",
        "SELECT COUNT(*) FROM mst.data_capture_field",
        "SELECT COUNT(*) FROM trn.work_order",
    ]:
        print(q, "->", conn.execute(text(q)).scalar())
