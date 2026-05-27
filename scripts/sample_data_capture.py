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
    print("process_library:")
    for r in conn.execute(text("SELECT process_id, process_code, process_name FROM mst.process_library LIMIT 5")):
        print(" ", r)
    print("templates:")
    for r in conn.execute(text("SELECT template_id, process_id, template_name, template_sequence FROM mst.data_capture_template ORDER BY template_sequence")):
        print(" ", r)
    print("fields:")
    for r in conn.execute(text("SELECT field_id, template_id, field_sequence, field_name, field_type, is_mandatory, min_value, max_value FROM mst.data_capture_field ORDER BY template_id, field_sequence")):
        print(" ", r)
